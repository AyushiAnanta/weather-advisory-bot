import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.llm import real_understand
from app.sop_loader import all_activity_tags, load_sops


QUERIES = [
    ("shuold i go cycling in chennai today", {}),
    ("Is it safe to cycle in Chennai today?", {}),
    (
        "what about this evening instead?",
        {
            "last_location_display": "Chennai, Tamil Nadu, India",
            "last_activity_tag": "cycling",
        },
    ),
    ("should I go for a run in Pune tomorrow morning?", {}),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure live time and activity extraction consistency.")
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    allowed_tags = all_activity_tags(load_sops(ROOT / "sops"))
    for message, summary in QUERIES:
        results = [
            real_understand(message, allowed_tags, summary)
            for _ in range(args.runs)
        ]
        print(f"Message: {message}")
        print(f"time_ref: {Counter(result['time_ref'] for result in results)}")
        print(f"activity_tag: {Counter(result['activity_tag'] for result in results)}")


if __name__ == "__main__":
    main()
