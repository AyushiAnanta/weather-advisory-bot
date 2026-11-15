from datetime import datetime

import pytest

from app.sop_loader import load_sops
from evals.run_evals import (
    cycling_branch_result,
    cycling_threshold,
    rank_by_remaining_max,
    remaining_max,
)


def test_remaining_max_ignores_past_and_none_values():
    facts = {
        "now": "2026-11-15T12:45",
        "hourly": {
            "time": [
                "2026-11-15T11:00",
                "2026-11-15T12:00",
                "2026-11-15T13:00",
                "2026-11-15T14:00",
            ],
            "wind_gusts_10m": [99, None, 31.5, 25],
        },
    }

    assert remaining_max(facts, "wind_gusts_10m") == 31.5


def test_remaining_max_returns_none_when_no_usable_value_is_left():
    facts = {
        "now": "2026-11-15T12:45",
        "hourly": {
            "time": ["2026-11-15T11:00", "2026-11-16T13:00"],
            "wind_gusts_10m": [50, 60],
        },
    }

    assert remaining_max(facts, "wind_gusts_10m") is None


def test_remaining_max_uses_the_date_in_facts_now():
    facts = {
        "now": "2026-11-16T10:00",
        "hourly": {
            "time": ["2026-11-15T11:00", "2026-11-16T09:00", "2026-11-16T10:00"],
            "wind_gusts_10m": [90, 80, 20],
        },
    }

    assert remaining_max(facts, "wind_gusts_10m") == 20


def test_rank_by_remaining_max_picks_largest_and_breaks_ties_alphabetically():
    facts = {
        "Bengaluru": {
            "now": "2026-11-15T10:00",
            "hourly": {"time": ["2026-11-15T10:00"], "wind_gusts_10m": [40]},
        },
        "Chennai": {
            "now": "2026-11-15T10:00",
            "hourly": {"time": ["2026-11-15T10:00"], "wind_gusts_10m": [45]},
        },
        "Ahmedabad": {
            "now": "2026-11-15T10:00",
            "hourly": {"time": ["2026-11-15T10:00"], "wind_gusts_10m": [45]},
        },
        "Delhi": {
            "now": "2026-11-15T10:00",
            "hourly": {"time": ["2026-11-15T09:00"], "wind_gusts_10m": [100]},
        },
    }

    assert rank_by_remaining_max(facts, "wind_gusts_10m") == "Ahmedabad"
    assert rank_by_remaining_max({"Delhi": facts["Delhi"]}, "wind_gusts_10m") is None


def test_cycling_threshold_reads_the_sop_file():
    wind_sop = next(sop for sop in load_sops("sops") if sop.id == "wind-cycling-001")
    hourly = next(
        condition
        for condition in (wind_sop.conditions.all or []) + (wind_sop.conditions.any or [])
        if condition.source == "hourly"
    )

    assert cycling_threshold() == hourly.value


def test_cycling_threshold_raises_when_wind_sop_is_missing(tmp_path):
    with pytest.raises(ValueError, match="wind-cycling-001.*not found"):
        cycling_threshold(tmp_path)


@pytest.mark.parametrize(
    ("gust", "threshold", "primary", "also", "kind", "reason", "expected"),
    [
        (45, 40, "wind-cycling-001", [], "advice", None, True),
        (39, 40, None, [], "no_match", "not_triggered", True),
        (45, 40, None, [], "advice", None, False),
        (39, 40, "wind-cycling-001", [], "no_match", "not_triggered", False),
        (39, 40, None, [], "advice", None, False),
    ],
)
def test_cycling_branch_result(gust, threshold, primary, also, kind, reason, expected):
    passed, _failure = cycling_branch_result(gust, threshold, primary, also, kind, reason)

    assert passed is expected


def test_cycling_branch_result_accepts_wind_sop_in_also_applies():
    passed, _detail = cycling_branch_result(45, 40, "compound-severe-weather-001", ["wind-cycling-001"], "advice", None)

    assert passed is True
