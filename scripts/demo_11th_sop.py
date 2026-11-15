import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.graph import build_graph
from app.llm import real_classify, real_compose, real_understand
from app.sop_loader import load_sops
from app.weather import WeatherResult, geocode


def main() -> None:
    sops = load_sops(ROOT / "sops")
    print(f"SOPs loaded from sops/: {len(sops)}")

    facts = json.loads(
        (ROOT / "evals" / "fixtures" / "benign.json").read_text(encoding="utf-8")
    )
    now = datetime.fromisoformat(facts["now"])
    hourly = facts["hourly"]
    hourly_times = hourly["time"]
    visibility = list(hourly.get("visibility", [20000] * len(hourly_times)))
    for index, timestamp in enumerate(hourly_times):
        if datetime.fromisoformat(timestamp) >= now:
            visibility[index] = 500
    hourly["visibility"] = visibility
    hourly["wind_gusts_10m"] = [20] * len(hourly_times)

    def fake_fetch_weather(_latitude, _longitude, _fields):
        return WeatherResult(ok=True, facts=facts)

    deps = {
        "understand": real_understand,
        "compose": real_compose,
        "classify": real_classify,
        "geocode": geocode,
        "fetch_weather": fake_fetch_weather,
    }
    graph = build_graph(sops, deps)
    result = graph.invoke(
        {"user_message": "Is it safe to cycle in Chennai today?"},
        config={"configurable": {"thread_id": "demo-11th-sop"}},
    )

    decision = result.get("decision") or {}
    primary = decision.get("primary") or {}
    matched_ids = [item.get("sop_id") for item in result.get("matched", [])]
    print("reply_kind:", result.get("reply_kind"))
    print("primary SOP id:", primary.get("sop_id"))
    print("matched ids:", matched_ids)
    print("full reply:")
    print(result.get("reply", ""))


if __name__ == "__main__":
    main()
