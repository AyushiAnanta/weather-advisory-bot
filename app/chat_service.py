from collections import deque
from pathlib import Path
import os
import sys
import time
from typing import Any, Callable

import yaml
from langgraph.checkpoint.memory import MemorySaver

from app.graph import build_graph
from app.llm import real_classify, real_compose, real_understand
from app.sop_loader import SOP, load_sops
from app.weather import fetch_weather, geocode


MESSAGES_PATH = Path(__file__).parents[1] / "config" / "messages.yaml"
WINDOW_SECONDS = 24 * 60 * 60


def _load_chat_messages() -> dict[str, str]:
    with MESSAGES_PATH.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    required = {
        "chat_rejected_empty",
        "chat_rejected_too_long",
        "chat_rejected_disabled",
        "chat_rejected_session_limit",
        "chat_rejected_daily_limit",
        "chat_error",
    }
    if not isinstance(raw, dict) or any(
        not isinstance(raw.get(key), str) or not raw[key].strip() for key in required
    ):
        raise ValueError("chat messages are missing required non-empty text")
    return {key: raw[key] for key in required}


def _env_limit(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


class ChatService:
    def __init__(self, deps: dict[str, Any], sops_dir: str = "sops", clock: Callable[[], float] = time.monotonic):
        self.messages = _load_chat_messages()
        self.sops: list[SOP] = load_sops(sops_dir)
        self._sops_by_id = {sop.id: sop for sop in self.sops}
        self.graph = build_graph(self.sops, deps, checkpointer=MemorySaver())
        self.clock = clock
        self._thread_turns: dict[str, int] = {}
        self._daily_requests: deque[float] = deque()

    def _response(
        self,
        thread_id: str,
        reply_body: str,
        reply_kind: str,
        failure_reason: str | None = None,
        sop: dict[str, str] | None = None,
        also_applies: list[str] | None = None,
        trigger_values: list[dict[str, Any]] | None = None,
        forecast: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "thread_id": thread_id,
            "reply_body": reply_body,
            "reply_kind": reply_kind,
            "sop": sop,
            "also_applies": also_applies or [],
            "trigger_values": trigger_values or [],
            "forecast": forecast,
            "failure_reason": failure_reason,
        }

    def _reject(self, thread_id: str, message_key: str, reason: str) -> dict[str, Any]:
        return self._response(
            thread_id,
            self.messages[message_key],
            "rejected",
            failure_reason=reason,
        )

    def ask(self, thread_id: str, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            return self._reject(thread_id, "chat_rejected_empty", "empty_message")
        if len(message) > _env_limit("CHAT_MAX_CHARS", 300):
            return self._reject(thread_id, "chat_rejected_too_long", "message_too_long")
        if os.environ.get("CHAT_DISABLED") == "1":
            return self._reject(thread_id, "chat_rejected_disabled", "chat_disabled")

        now = self.clock()
        while self._daily_requests and now - self._daily_requests[0] >= WINDOW_SECONDS:
            self._daily_requests.popleft()

        if self._thread_turns.get(thread_id, 0) >= _env_limit("CHAT_MAX_TURNS_PER_SESSION", 20):
            return self._reject(thread_id, "chat_rejected_session_limit", "session_limit")
        if len(self._daily_requests) >= _env_limit("CHAT_MAX_PER_DAY", 500):
            return self._reject(thread_id, "chat_rejected_daily_limit", "daily_limit")

        self._thread_turns[thread_id] = self._thread_turns.get(thread_id, 0) + 1
        self._daily_requests.append(now)
        try:
            state = self.graph.invoke(
                {"user_message": message},
                config={"configurable": {"thread_id": thread_id}},
            )
            decision = state.get("decision") or {}
            primary = decision.get("primary")
            sop_info = None
            if primary:
                sop_info = {
                    "id": primary["sop_id"],
                    "severity": primary["severity"],
                    "category": primary["category"],
                }
            elif state.get("reply_kind") == "classifier":
                classifier_sop = self._sops_by_id.get(state.get("classifier_sop_id"))
                if classifier_sop is not None:
                    sop_info = {
                        "id": classifier_sop.id,
                        "severity": classifier_sop.severity,
                        "category": classifier_sop.category,
                    }

            trigger_values = [
                {"field": item.get("field"), "agg": item.get("agg"), "actual": item.get("actual")}
                for item in state.get("trigger_values", [])
            ]
            location = state.get("location")
            facts = state.get("facts")
            forecast = None
            if location and facts and facts.get("now") is not None:
                forecast = {
                    "location": location.get("display"),
                    "as_of": facts["now"],
                    "timezone": facts.get("timezone"),
                }
            return self._response(
                thread_id,
                state.get("reply_body", state.get("reply", "")),
                state.get("reply_kind", "error"),
                failure_reason=state.get("failure_reason"),
                sop=sop_info,
                also_applies=decision.get("also_applies", []),
                trigger_values=trigger_values,
                forecast=forecast,
            )
        except Exception as exc:
            print(f"Chat graph exception: {exc}", file=sys.stderr)
            return self._response(
                thread_id,
                self.messages["chat_error"],
                "error",
                failure_reason="unexpected_exception",
            )


def build_default_service(sops_dir: str = "sops", clock: Callable[[], float] = time.monotonic) -> ChatService:
    deps = {
        "understand": real_understand,
        "compose": real_compose,
        "classify": real_classify,
        "geocode": geocode,
        "fetch_weather": fetch_weather,
    }
    return ChatService(deps, sops_dir=sops_dir, clock=clock)
