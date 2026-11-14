from datetime import datetime

import pytest

from app.classifier import classifier_facts, outcome_text
from app.matcher import match_sops
from app.sop_loader import load_sops


PICNIC_ID = "picnic-fuzzy-001"
SOPS = load_sops("sops")
PICNIC_SOP = next(sop for sop in SOPS if sop.id == PICNIC_ID)
NOW = datetime.fromisoformat("2026-11-13T12:00")


def classifier_weather_facts(include_uv=True):
    hourly = {
        "time": [f"2026-11-13T{hour:02}:00" for hour in range(24)],
        "precipitation_probability": [10] * 24,
        "temperature_2m": [20] * 24,
        "wind_gusts_10m": [12] * 24,
    }
    hourly["temperature_2m"][13] = 18
    hourly["temperature_2m"][15] = 32
    hourly["wind_gusts_10m"][16] = 24
    if include_uv:
        hourly["uv_index"] = [3] * 24
        hourly["uv_index"][13] = 6
    return {"now": "2026-11-13T12:00", "hourly": hourly}


def test_match_sops_never_returns_classifier_sop():
    facts = classifier_weather_facts()

    matched = match_sops([PICNIC_SOP], facts, "picnic", NOW)

    assert matched == []


def test_classifier_facts_returns_exact_hourly_aggregates():
    actual = classifier_facts(PICNIC_SOP, classifier_weather_facts(), NOW)

    assert actual == [
        {"field": "precipitation_probability", "agg": "max", "actual": 10},
        {"field": "temperature_2m", "agg": "min", "actual": 18},
        {"field": "temperature_2m", "agg": "max", "actual": 32},
        {"field": "wind_gusts_10m", "agg": "max", "actual": 24},
        {"field": "uv_index", "agg": "max", "actual": 6},
    ]


def test_classifier_facts_returns_none_for_missing_data():
    actual = classifier_facts(PICNIC_SOP, classifier_weather_facts(include_uv=False), NOW)

    assert actual[-1] == {"field": "uv_index", "agg": "max", "actual": None}


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("suitable", "Conditions look comfortable for a picnic today."),
        (
            "marginal",
            "Conditions are mixed for a picnic today. If you go, keep an eye on the forecast and have a backup plan.",
        ),
        (
            "unsuitable",
            "Conditions look poor for a picnic today. Consider postponing or choosing an indoor alternative.",
        ),
    ],
)
def test_outcome_text_returns_exact_configured_text(label, expected):
    assert outcome_text(PICNIC_SOP, label) == expected


@pytest.mark.parametrize("label", ["excellent", "SUITABLE", " suitable", None])
def test_outcome_text_rejects_invalid_labels(label):
    with pytest.raises(ValueError):
        outcome_text(PICNIC_SOP, label)
