import argparse
import json
from pathlib import Path

from app.sop_loader import load_sops, required_fields
from app.weather import fetch_weather, geocode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    location = geocode(args.city)
    if not location.ok:
        print(location.reason)
        return 1

    weather = fetch_weather(
        location.latitude,
        location.longitude,
        required_fields(load_sops("sops")),
    )
    if not weather.ok:
        print(weather.reason)
        return 1

    output = {
        "city_label": location.display,
        "recorded_at_note": "recorded API response",
        "facts": weather.facts,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
