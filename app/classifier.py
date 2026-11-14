from datetime import datetime
from types import SimpleNamespace
from typing import Any

from app.matcher import evaluate_condition
from app.sop_loader import SOP


OUTCOME_LABELS = {"suitable", "marginal", "unsuitable"}


def classifier_facts(sop: SOP, facts: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Return deterministic hourly aggregates for a classifier SOP's requested facts."""
    if sop.kind != "classifier" or sop.classifier is None:
        raise ValueError("SOP must be a classifier")

    results: list[dict[str, Any]] = []
    for fact in sop.classifier.facts:
        condition = SimpleNamespace(
            source=fact.source,
            field=fact.field,
            agg=fact.agg,
            window=fact.window,
            op="==",
            value=0,
        )
        _, actual = evaluate_condition(condition, facts, now)
        results.append({"field": fact.field, "agg": fact.agg, "actual": actual})
    return results


def outcome_text(sop: SOP, label: str) -> str:
    """Return the configured exact text for a valid classifier label."""
    if not isinstance(label, str) or label not in OUTCOME_LABELS:
        raise ValueError(f"invalid classifier outcome label: {label!r}")
    if sop.kind != "classifier" or sop.classifier is None:
        raise ValueError("SOP must be a classifier")
    return sop.classifier.outcomes[label]
