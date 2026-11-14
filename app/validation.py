import re
from dataclasses import dataclass
from typing import Any


_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?![A-Za-z0-9_])")
_SOP_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[a-z]+(?:-[a-z]+)*-\d{3}(?![A-Za-z0-9_])")


def extract_numbers(text: str) -> list[float]:
    return [float(match.group(0)) for match in _NUMBER_PATTERN.finditer(text)]


def validate_reply(reply: str, allowed_numbers: set[float], matched_ids: list[str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    mentioned_ids = set(_SOP_ID_PATTERN.findall(reply))
    unknown_ids = sorted(mentioned_ids - set(matched_ids))
    if unknown_ids:
        reasons.append(f"reply cites unmatched SOP id(s): {', '.join(unknown_ids)}")

    text_without_ids = reply
    for sop_id in matched_ids:
        text_without_ids = text_without_ids.replace(sop_id, " ")
    text_without_ids = _SOP_ID_PATTERN.sub(" ", text_without_ids)
    for number in extract_numbers(text_without_ids):
        if number not in allowed_numbers:
            reasons.append(f"reply contains unsupported number: {number:g}")
    return not reasons, reasons


def _primary(decision: Any) -> Any:
    if isinstance(decision, dict):
        return decision["primary"]
    return decision.primary


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key)


def allowed_numbers_for(decision: Any, trigger_values: list[dict[str, Any]], location_display: str) -> set[float]:
    del location_display
    primary = _primary(decision)
    guidance_numbers = extract_numbers(_get(primary, "guidance"))
    trigger_numbers = [
        float(item["actual"])
        for item in trigger_values
        if isinstance(item.get("actual"), (int, float)) and not isinstance(item.get("actual"), bool)
    ]
    return set(guidance_numbers + trigger_numbers)


def build_template_reply(decision: Any, location_display: str) -> str:
    primary = _primary(decision)
    guidance = _get(primary, "guidance")
    trigger_values = _get(primary, "trigger_values")
    details = [
        f"{item['field']} {item.get('agg', item.get('op', ''))} was {item['actual']}"
        for item in trigger_values
    ]
    reply = f"{location_display}: {guidance}"
    if details:
        reply += " Forecast facts: " + "; ".join(details) + "."
    return reply
