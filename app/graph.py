from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.classifier import classifier_facts, outcome_text
from app.matcher import MatchedSOP, ResolvedDecision, match_sops as matcher_match_sops, resolve
from app.messages import load_messages
from app.sop_loader import SOP, all_activity_tags, required_fields
from app.validation import allowed_numbers_for, build_template_reply, validate_reply


@dataclass(frozen=True)
class PreviousDecisionSummary:
    sop_id: str
    severity: str
    location_display: str
    activity_tag: str | None
    forecast_now: str


@dataclass(frozen=True)
class ComposeInput:
    primary_guidance: str
    primary_sop_id: str
    primary_severity: str
    also_applies: list[str]
    trigger_values: list[dict[str, Any]]
    location_display: str
    previous_decision: PreviousDecisionSummary | None


class GraphState(TypedDict, total=False):
    user_message: str
    extracted: dict[str, Any]
    city_text: str | None
    activity_tag: str | None
    time_ref: str | None
    is_followup: bool
    location: dict[str, Any] | None
    facts: dict[str, Any] | None
    matched: list[dict[str, Any]]
    decision: dict[str, Any] | None
    trigger_values: list[dict[str, Any]]
    failure_reason: str | None
    reply: str
    reply_kind: str
    cited_sop_ids: list[str]
    classifier_sop_id: str | None
    history: list[dict[str, Any]]
    last_city_text: str | None
    last_location: dict[str, Any] | None
    last_activity_tag: str | None
    last_decision: dict[str, Any] | None


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("expected a dictionary or dataclass result")


def _matched_to_dict(item: MatchedSOP) -> dict[str, Any]:
    return {
        "sop_id": item.sop_id,
        "category": item.category,
        "severity": item.severity,
        "applies_to": list(item.applies_to),
        "guidance": item.guidance,
        "trigger_values": item.trigger_values,
        "override": item.override,
    }


def _matched_from_dict(item: dict[str, Any]) -> MatchedSOP:
    return MatchedSOP(
        sop_id=item["sop_id"],
        category=item["category"],
        severity=item["severity"],
        applies_to=item["applies_to"],
        guidance=item["guidance"],
        trigger_values=item["trigger_values"],
        override=item.get("override", False),
    )


def _decision_to_dict(decision: ResolvedDecision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "primary": _matched_to_dict(decision.primary),
        "also_applies": list(decision.also_applies),
    }


def _classifier_applies(sop: SOP, activity_tag: str | None) -> bool:
    if activity_tag is None:
        return "*" in sop.applies_to
    return activity_tag in sop.applies_to or "*" in sop.applies_to


def build_graph(sops: list[SOP], deps: dict[str, Any], checkpointer=None):
    fields = required_fields(sops)
    allowed_tags = all_activity_tags(sops)
    messages = load_messages()
    classifiers_by_id = {sop.id: sop for sop in sops if sop.kind == "classifier"}

    def begin_turn(state: GraphState) -> dict[str, Any]:
        return {
            "reply": "",
            "reply_kind": "",
            "matched": [],
            "decision": None,
            "failure_reason": None,
            "cited_sop_ids": [],
            "trigger_values": [],
            "extracted": {},
            "city_text": None,
            "activity_tag": None,
            "time_ref": None,
            "is_followup": False,
            "location": None,
            "facts": None,
            "classifier_sop_id": None,
        }

    def understand_node(state: GraphState) -> dict[str, Any]:
        session_summary = {
            "last_location_display": (state.get("last_location") or {}).get("display"),
            "last_activity_tag": state.get("last_activity_tag"),
        }
        extracted = deps["understand"](
            state.get("user_message", ""),
            allowed_tags,
            session_summary,
        )
        return {"extracted": extracted}

    def merge_context(state: GraphState) -> dict[str, Any]:
        extracted = state.get("extracted") or {}
        # time_ref is retained for the next stage; applied in 5B.
        return {
            "city_text": extracted.get("city") or state.get("last_city_text"),
            "activity_tag": extracted.get("activity_tag") or state.get("last_activity_tag"),
            "time_ref": extracted.get("time_ref"),
            "is_followup": bool(extracted.get("is_followup", False)),
        }

    def route_city(state: GraphState) -> str:
        return "geocode" if state.get("city_text") else "clarify"

    def clarify(state: GraphState) -> dict[str, Any]:
        return {"reply": messages["clarify_city"], "reply_kind": "clarify"}

    def geocode_node(state: GraphState) -> dict[str, Any]:
        city_text = state["city_text"]
        old_location = state.get("last_location")
        if city_text == state.get("last_city_text") and old_location:
            return {"location": old_location, "failure_reason": None}

        result = _to_dict(deps["geocode"](city_text))
        if not result.get("ok"):
            return {"failure_reason": result.get("reason") or "geocoding_unavailable"}
        return {
            "location": result,
            "last_city_text": city_text,
            "last_location": result,
            "failure_reason": None,
        }

    def after_geocode(state: GraphState) -> str:
        return "fallback" if state.get("failure_reason") else "fetch_weather"

    def fetch_weather_node(state: GraphState) -> dict[str, Any]:
        location = state["location"]
        result = _to_dict(deps["fetch_weather"](location["latitude"], location["longitude"], fields))
        if not result.get("ok") or not isinstance(result.get("facts"), dict):
            return {"failure_reason": result.get("reason") or "weather_unavailable"}
        return {"facts": result["facts"], "failure_reason": None}

    def after_fetch(state: GraphState) -> str:
        return "fallback" if state.get("failure_reason") else "match_sops"

    def fallback(state: GraphState) -> dict[str, Any]:
        reason = state.get("failure_reason")
        message_key = reason if reason in messages else "weather_unavailable"
        return {"reply": messages[message_key], "reply_kind": "fallback"}

    def match_node(state: GraphState) -> dict[str, Any]:
        facts = state["facts"]
        now = datetime.fromisoformat(facts["now"])
        matched = matcher_match_sops(sops, facts, state.get("activity_tag"), now)
        serialized = []
        for item in matched:
            data = _matched_to_dict(item)
            source_sop = next(sop for sop in sops if sop.id == item.sop_id)
            conditions = (source_sop.conditions.all or []) + (source_sop.conditions.any or [])
            for trigger in data["trigger_values"]:
                condition = next(
                    (
                        candidate
                        for candidate in conditions
                        if candidate.field == trigger["field"]
                        and candidate.op == trigger["op"]
                        and candidate.value == trigger["value"]
                    ),
                    None,
                )
                if condition is not None and hasattr(condition, "agg"):
                    trigger["agg"] = condition.agg
            serialized.append(data)
        return {"matched": serialized}

    def resolve_node(state: GraphState) -> dict[str, Any]:
        matched = [_matched_from_dict(item) for item in state.get("matched", [])]
        decision = resolve(matched)
        classifier_id = None
        if decision is None:
            classifier_id = next(
                (
                    sop.id
                    for sop in sops
                    if sop.kind == "classifier" and _classifier_applies(sop, state.get("activity_tag"))
                ),
                None,
            )
        serialized = _decision_to_dict(decision)
        trigger_values = serialized["primary"]["trigger_values"] if serialized else []
        cited = (
            [serialized["primary"]["sop_id"], *serialized["also_applies"]]
            if serialized
            else []
        )
        return {
            "decision": serialized,
            "trigger_values": trigger_values,
            "cited_sop_ids": cited,
            "classifier_sop_id": classifier_id,
        }

    def route_decision(state: GraphState) -> str:
        if state.get("decision"):
            return "compose"
        return "classify" if state.get("classifier_sop_id") else "no_match"

    def classify_node(state: GraphState) -> dict[str, Any]:
        sop = classifiers_by_id[state["classifier_sop_id"]]
        now = datetime.fromisoformat(state["facts"]["now"])
        calculated_facts = classifier_facts(sop, state["facts"], now)
        classify_input = {"rubric": sop.classifier.rubric, "facts": calculated_facts}
        for attempt in range(2):
            try:
                label = deps["classify"](classify_input)
                text = outcome_text(sop, label)
            except ValueError:
                if attempt == 0:
                    continue
                return {"reply_kind": "classify_failed"}
            return {
                "reply": text,
                "reply_kind": "classifier",
                "cited_sop_ids": [sop.id],
                "trigger_values": calculated_facts,
                "citation_severity": sop.severity,
            }
        return {"reply_kind": "classify_failed"}

    def after_classify(state: GraphState) -> str:
        return "finalize" if state.get("reply_kind") == "classifier" else "no_match"

    def no_match(state: GraphState) -> dict[str, Any]:
        return {"reply": messages["no_match"], "reply_kind": "no_match"}

    def compose_node(state: GraphState) -> dict[str, Any]:
        decision = state["decision"]
        primary = decision["primary"]
        last = state.get("last_decision")
        previous = PreviousDecisionSummary(**last) if last else None
        compose_input = ComposeInput(
            primary_guidance=primary["guidance"],
            primary_sop_id=primary["sop_id"],
            primary_severity=primary["severity"],
            also_applies=list(decision["also_applies"]),
            trigger_values=list(state.get("trigger_values", [])),
            location_display=state["location"]["display"],
            previous_decision=previous,
        )
        return {"reply": deps["compose"](compose_input)}

    def validate_node(state: GraphState) -> dict[str, Any]:
        decision = state["decision"]
        reply = state.get("reply", "")
        ids = state.get("cited_sop_ids", [])
        allowed = allowed_numbers_for(decision, state.get("trigger_values", []), state["location"]["display"])
        ok, _reasons = validate_reply(reply, allowed, ids)
        if ok:
            return {"reply_kind": "advice"}
        return {
            "reply": build_template_reply(decision, state["location"]["display"]),
            "reply_kind": "template",
        }

    def finalize(state: GraphState) -> dict[str, Any]:
        reply = state.get("reply", "")
        kind = state.get("reply_kind")
        decision = state.get("decision")
        location = state.get("location")
        facts = state.get("facts")
        citation_ids = list(state.get("cited_sop_ids", []))
        last_decision = state.get("last_decision")

        if kind in {"advice", "template"} and decision:
            primary = decision["primary"]
            lines = [f"Policy: {primary['sop_id']} ({primary['severity']})"]
            if decision["also_applies"]:
                lines.append("Also applies: " + ", ".join(decision["also_applies"]))
            lines.append(
                f"Forecast: {location['display']}, as of {facts['now']} ({facts.get('timezone')})"
            )
            reply = reply.rstrip() + "\n\n" + "\n".join(lines)
            last_decision = {
                "sop_id": primary["sop_id"],
                "severity": primary["severity"],
                "location_display": location["display"],
                "activity_tag": state.get("activity_tag"),
                "forecast_now": facts["now"],
            }
        elif kind == "classifier" and location and facts:
            sop = classifiers_by_id[citation_ids[0]]
            lines = [f"Policy: {sop.id} ({sop.severity})"]
            lines.append(
                f"Forecast: {location['display']}, as of {facts['now']} ({facts.get('timezone')})"
            )
            reply = reply.rstrip() + "\n\n" + "\n".join(lines)
            last_decision = {
                "sop_id": sop.id,
                "severity": sop.severity,
                "location_display": location["display"],
                "activity_tag": state.get("activity_tag"),
                "forecast_now": facts["now"],
            }

        history = list(state.get("history", []))
        history.append(
            {
                "reply": reply,
                "reply_kind": kind,
                "cited_sop_ids": citation_ids,
            }
        )
        updates: dict[str, Any] = {"reply": reply, "history": history, "last_decision": last_decision}
        if state.get("city_text"):
            updates["last_city_text"] = state["city_text"]
        if state.get("activity_tag"):
            updates["last_activity_tag"] = state["activity_tag"]
        if location and location.get("ok"):
            updates["last_location"] = location
        return updates

    graph = StateGraph(GraphState)
    graph.add_node("begin_turn", begin_turn)
    graph.add_node("understand", understand_node)
    graph.add_node("merge_context", merge_context)
    graph.add_node("clarify", clarify)
    graph.add_node("geocode", geocode_node)
    graph.add_node("fetch_weather", fetch_weather_node)
    graph.add_node("fallback", fallback)
    graph.add_node("match_sops", match_node)
    graph.add_node("resolve", resolve_node)
    graph.add_node("classify", classify_node)
    graph.add_node("no_match", no_match)
    graph.add_node("compose", compose_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "begin_turn")
    graph.add_edge("begin_turn", "understand")
    graph.add_edge("understand", "merge_context")
    graph.add_conditional_edges("merge_context", route_city, {"clarify": "clarify", "geocode": "geocode"})
    graph.add_edge("clarify", "finalize")
    graph.add_conditional_edges("geocode", after_geocode, {"fallback": "fallback", "fetch_weather": "fetch_weather"})
    graph.add_conditional_edges("fetch_weather", after_fetch, {"fallback": "fallback", "match_sops": "match_sops"})
    graph.add_edge("fallback", "finalize")
    graph.add_edge("match_sops", "resolve")
    graph.add_conditional_edges(
        "resolve",
        route_decision,
        {"compose": "compose", "classify": "classify", "no_match": "no_match"},
    )
    graph.add_conditional_edges("classify", after_classify, {"finalize": "finalize", "no_match": "no_match"})
    graph.add_edge("no_match", "finalize")
    graph.add_edge("compose", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
