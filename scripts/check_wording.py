import os
from collections import Counter
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

load_dotenv(ROOT / ".env")

from app.graph import build_graph
from app.llm import real_classify, real_compose, real_understand
from app.sop_loader import load_sops
from app.weather import fetch_weather, geocode


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Add it to .env or the environment.")

    deps = {
        "understand": real_understand,
        "compose": real_compose,
        "classify": real_classify,
        "geocode": geocode,
        "fetch_weather": fetch_weather,
    }
    graph = build_graph(load_sops(ROOT / "sops"), deps, checkpointer=MemorySaver())
    reply_kinds: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()
    phrase_denominators: Counter[str] = Counter()

    def run_turn(scenario: str, run_number: int, thread_id: str, message: str, turn: int = 1):
        result = graph.invoke(
            {"user_message": message},
            config={"configurable": {"thread_id": thread_id}},
        )
        reply = result.get("reply", "")
        reply_kind = result.get("reply_kind")
        evaluated_for = result.get("evaluated_for")
        no_match_reason = result.get("no_match_reason")
        print(
            f"{scenario} run {run_number} turn {turn}: reply_kind={reply_kind}, "
            f"evaluated_for={evaluated_for}, no_match_reason={no_match_reason}"
        )
        print(f"reply: {reply}")
        reply_kinds[reply_kind] += 1

        for phrase in ("have reached", "currently", "actual value"):
            phrase_denominators[phrase] += 1
            phrase_counts[phrase] += phrase in reply.lower()
        if scenario in {"B", "D"}:
            phrase_denominators['"tomorrow" (B and D)'] += 1
            phrase_counts['"tomorrow" (B and D)'] += "tomorrow" in reply.lower()
            for phrase in ("today", "this evening", "remain", "at least", "similar"):
                phrase_denominators[f'"{phrase}" (B and D)'] += 1
                phrase_counts[f'"{phrase}" (B and D)'] += phrase in reply.lower()
        if scenario == "C" and turn == 2:
            phrase_denominators['"this evening" (C turn 2)'] += 1
            phrase_counts['"this evening" (C turn 2)'] += "this evening" in reply.lower()
        return result

    for run_number in range(1, 6):
        run_turn(
            "A",
            run_number,
            uuid.uuid4().hex,
            "Is it safe to cycle in Chennai today?",
        )
        run_turn(
            "B",
            run_number,
            uuid.uuid4().hex,
            "Is it safe to cycle in Chennai tomorrow?",
        )

        thread_id = uuid.uuid4().hex
        run_turn(
            "C",
            run_number,
            thread_id,
            "Is it safe to cycle in Chennai today?",
            turn=1,
        )
        run_turn(
            "C",
            run_number,
            thread_id,
            "what about this evening instead?",
            turn=2,
        )
        run_turn(
            "D",
            run_number,
            uuid.uuid4().hex,
            "Is it safe to go for a picnic in Kolkata tomorrow?",
        )

    print("\nReply-kind counts:")
    print(reply_kinds)
    print("Phrase counts (matching replies / checked replies):")
    for phrase, count in phrase_counts.items():
        print(f"{phrase}: {count}/{phrase_denominators[phrase]}")


if __name__ == "__main__":
    main()
