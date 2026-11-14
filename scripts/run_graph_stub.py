import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from app.graph import build_graph
from app.matcher import resolve
from app.sop_loader import load_sops
from app.stubs import stub_compose
from app.weather import fetch_weather, geocode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--thread", required=True)
    args = parser.parse_args()

    extraction = {
        "city": args.city,
        "activity_tag": args.activity,
        "time_ref": None,
        "is_followup": False,
    }
    deps = {
        "geocode": geocode,
        "fetch_weather": fetch_weather,
        "understand": lambda _message, _allowed_tags, _summary: extraction,
        "compose": stub_compose,
        "classify": lambda _classify_input: "marginal",
    }
    graph = build_graph(load_sops("sops"), deps)
    result = graph.invoke(
        {"user_message": ""},
        config={"configurable": {"thread_id": args.thread}},
    )
    print("reply:", result.get("reply"))
    print("reply_kind:", result.get("reply_kind"))
    print("cited_sop_ids:", result.get("cited_sop_ids", []))


if __name__ == "__main__":
    main()
