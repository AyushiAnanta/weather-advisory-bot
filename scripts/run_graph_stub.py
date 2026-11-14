import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import argparse
import os

from app.graph import build_graph
from app.llm import real_classify, real_compose, real_understand
from app.sop_loader import load_sops
from app.weather import fetch_weather, geocode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--thread", required=True)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Add it to .env or the environment.")

    deps = {
        "understand": real_understand,
        "compose": real_compose,
        "classify": real_classify,
        "geocode": geocode,
        "fetch_weather": fetch_weather,
    }
    graph = build_graph(load_sops("sops"), deps)
    user_message = f"Is it safe to {args.activity} in {args.city}?"
    result = graph.invoke(
        {"user_message": user_message},
        config={"configurable": {"thread_id": args.thread}},
    )
    print("reply:", result.get("reply"))
    print("reply_kind:", result.get("reply_kind"))
    print("cited_sop_ids:", result.get("cited_sop_ids", []))


if __name__ == "__main__":
    main()
