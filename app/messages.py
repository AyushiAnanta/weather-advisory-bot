from pathlib import Path

import yaml


MESSAGE_KEYS = {
    "clarify_city",
    "location_not_found",
    "geocoding_unavailable",
    "weather_unavailable",
    "no_match",
}
DEFAULT_MESSAGES_PATH = Path(__file__).parents[1] / "config" / "messages.yaml"


def load_messages(path: str | Path = DEFAULT_MESSAGES_PATH) -> dict[str, str]:
    with Path(path).open(encoding="utf-8") as file:
        messages = yaml.safe_load(file)
    if not isinstance(messages, dict) or any(
        key not in messages or not isinstance(messages[key], str) or not messages[key].strip()
        for key in MESSAGE_KEYS
    ):
        raise ValueError("messages file must define every required key with non-empty text")
    return {key: messages[key] for key in MESSAGE_KEYS}
