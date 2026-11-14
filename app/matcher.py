from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.sop_loader import SOP


@dataclass(frozen=True)
class MatchedSOP:
    sop_id: str
    category: str
    severity: str
    applies_to: list[str]
    guidance: str
    trigger_values: list[dict[str, Any]]
    override: bool = False


@dataclass(frozen=True)
class ResolvedDecision:
    primary: MatchedSOP
    also_applies: list[str]


def _apply_operator(actual: Any, op: str, expected: Any) -> bool:
    if op == ">":
        return actual > expected
    if op == ">=":
        return actual >= expected
    if op == "<":
        return actual < expected
    if op == "<=":
        return actual <= expected
    if op == "==":
        return actual == expected
    if op == "in":
        return actual in expected
    return False


def evaluate_condition(condition: Any, facts: dict[str, Any], now: datetime) -> tuple[bool, Any | None]:
    source = condition.source
    field = condition.field

    if source == "current":
        current = facts.get("current", {})
        actual = current.get(field) if isinstance(current, dict) else None
        if actual is None:
            return False, None
        return _apply_operator(actual, condition.op, condition.value), actual

    if source == "hourly":
        hourly = facts.get("hourly", {})
        if not isinstance(hourly, dict):
            return False, None
        times = hourly.get("time")
        values = hourly.get(field)
        if not isinstance(times, list) or not isinstance(values, list):
            return False, None

        window = condition.window
        start_hour = window.start_hour if window is not None else now.hour
        end_hour = window.end_hour if window is not None else 23
        target_date = now.date()
        if window is not None and window.day == "tomorrow":
            target_date += timedelta(days=1)

        selected: list[Any] = []
        for index, timestamp in enumerate(times):
            if index >= len(values) or not isinstance(timestamp, str):
                continue
            try:
                timestamp_date = datetime.fromisoformat(timestamp)
            except ValueError:
                continue
            if (
                timestamp_date.date() == target_date
                and start_hour <= timestamp_date.hour <= end_hour
                and (window is None or target_date != now.date() or timestamp_date.hour >= now.hour)
            ):
                value = values[index]
                if value is not None:
                    selected.append(value)

        if not selected:
            return False, None
        aggregation = condition.agg
        if aggregation == "max":
            actual = max(selected)
        elif aggregation == "min":
            actual = min(selected)
        elif aggregation == "mean":
            actual = sum(selected) / len(selected)
        elif aggregation == "sum":
            actual = sum(selected)
        else:
            return False, None
        return _apply_operator(actual, condition.op, condition.value), actual

    if source == "daily":
        daily = facts.get("daily", {})
        values = daily.get(field) if isinstance(daily, dict) else None
        day_index = {"today": 0, "tomorrow": 1}.get(condition.day)
        if not isinstance(values, list) or day_index is None or day_index >= len(values):
            return False, None
        actual = values[day_index]
        if actual is None:
            return False, None
        return _apply_operator(actual, condition.op, condition.value), actual

    return False, None


def _conditions(sop: SOP) -> tuple[list[Any], list[Any]]:
    return sop.conditions.all or [], sop.conditions.any or []


def sop_matches(sop: SOP, facts: dict[str, Any], now: datetime) -> tuple[bool, list[dict[str, Any]]]:
    all_conditions, any_conditions = _conditions(sop)
    evaluations: dict[int, tuple[bool, Any | None]] = {}
    for index, condition in enumerate(all_conditions + any_conditions):
        evaluations[index] = evaluate_condition(condition, facts, now)

    all_results = [evaluations[index][0] for index in range(len(all_conditions))]
    any_results = [
        evaluations[index][0]
        for index in range(len(all_conditions), len(all_conditions) + len(any_conditions))
    ]
    all_match = all(all_results)
    any_match = any(any_results) if any_conditions else True

    trigger_values: list[dict[str, Any]] = []
    for index, condition in enumerate(all_conditions + any_conditions):
        matched, actual = evaluations[index]
        if matched:
            trigger_values.append(
                {
                    "source": condition.source,
                    "field": condition.field,
                    "op": condition.op,
                    "value": condition.value,
                    "actual": actual,
                }
            )
    return all_match and any_match, trigger_values


def match_sops(
    sops: list[SOP],
    facts: dict[str, Any],
    activity_tag: str | None,
    now: datetime,
) -> list[MatchedSOP]:
    matched_sops: list[MatchedSOP] = []
    for sop in sops:
        if sop.kind == "classifier":
            continue
        has_wildcard = "*" in sop.applies_to
        if activity_tag is None:
            eligible = has_wildcard
        else:
            eligible = activity_tag in sop.applies_to or has_wildcard
        if not eligible:
            continue
        matched, trigger_values = sop_matches(sop, facts, now)
        if matched:
            matched_sops.append(
                MatchedSOP(
                    sop_id=sop.id,
                    category=sop.category,
                    severity=sop.severity,
                    applies_to=list(sop.applies_to),
                    guidance=sop.guidance,
                    trigger_values=trigger_values,
                    override=sop.override,
                )
            )
    return matched_sops


def resolve(matched: list[MatchedSOP]) -> ResolvedDecision | None:
    if not matched:
        return None
    severity_rank = {"high": 3, "medium": 2, "low": 1, "info": 0}
    ordered = sorted(
        matched,
        key=lambda item: (
            not item.override,
            -severity_rank[item.severity],
            "*" in item.applies_to,
            item.sop_id,
        ),
    )
    return ResolvedDecision(
        primary=ordered[0],
        also_applies=[item.sop_id for item in ordered[1:]],
    )
