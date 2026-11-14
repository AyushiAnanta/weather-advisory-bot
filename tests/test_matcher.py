from datetime import datetime
from pathlib import Path

import pytest

from app.matcher import MatchedSOP, evaluate_condition, match_sops, resolve, sop_matches
from app.sop_loader import SOP, load_sops


def make_sop(
    sop_id="sample",
    severity="high",
    applies_to=None,
    all_conditions=None,
    any_conditions=None,
    override=False,
):
    return SOP.model_validate(
        {
            "id": sop_id,
            "category": "exercise",
            "severity": severity,
            "applies_to": applies_to if applies_to is not None else ["cycling"],
            "conditions": {"all": all_conditions, "any": any_conditions},
            "guidance": "Example guidance",
            "override": override,
        }
    )


def current_condition(field="temperature_2m", op=">", value=0):
    return {"source": "current", "field": field, "op": op, "value": value}


def hourly_condition(field, agg, op, value, window=None):
    condition = {
        "source": "hourly",
        "field": field,
        "agg": agg,
        "op": op,
        "value": value,
    }
    if window is not None:
        condition["window"] = window
    return condition


def base_facts(now="2026-11-13T10:00:00"):
    return {
        "now": now,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {"time": []},
        "daily": {"time": []},
    }


def now_from(facts):
    return datetime.fromisoformat(facts["now"])


def test_wind_cycling_matches_when_gust_is_45():
    facts = base_facts()
    facts["hourly"].update({"time": ["2026-11-13T12:00"], "wind_gusts_10m": [45]})
    sop = make_sop(
        sop_id="wind-cycling-001",
        severity="high",
        applies_to=["cycling"],
        all_conditions=[hourly_condition("wind_gusts_10m", "max", ">=", 40)],
    )

    matched, triggers = sop_matches(sop, facts, now_from(facts))

    assert matched is True
    assert triggers == [
        {
            "source": "hourly",
            "field": "wind_gusts_10m",
            "op": ">=",
            "value": 40,
            "actual": 45,
        }
    ]


def test_uv_window_matches_when_value_8_is_inside_window():
    facts = base_facts()
    facts["hourly"].update(
        {
            "time": [
                "2026-11-13T10:00",
                "2026-11-13T11:00",
                "2026-11-13T16:00",
                "2026-11-13T17:00",
            ],
            "uv_index": [8, 2, 8, 8],
        }
    )
    sop = make_sop(
        sop_id="uv-exercise-001",
        severity="medium",
        applies_to=["outdoor_exercise"],
        all_conditions=[
            hourly_condition(
                "uv_index",
                "max",
                ">=",
                8,
                {"day": "today", "start_hour": 11, "end_hour": 16},
            )
        ],
    )

    assert sop_matches(sop, facts, now_from(facts))[0] is True


def test_uv_window_does_not_match_when_only_8_is_outside_window():
    facts = base_facts()
    facts["hourly"].update(
        {"time": ["2026-11-13T10:00", "2026-11-13T17:00"], "uv_index": [8, 8]}
    )
    sop = make_sop(
        applies_to=["outdoor_exercise"],
        all_conditions=[
            hourly_condition(
                "uv_index",
                "max",
                ">=",
                8,
                {"day": "today", "start_hour": 11, "end_hour": 16},
            )
        ],
    )

    assert sop_matches(sop, facts, now_from(facts))[0] is False


def test_explicit_hourly_window_does_not_match_after_its_hours():
    facts = base_facts(now="2026-11-13T17:00")
    facts["hourly"].update(
        {
            "time": [f"2026-11-13T{hour:02}:00" for hour in range(24)],
            "uv_index": [9] * 24,
        }
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition("uv_index", "max", ">=", 8, {"day": "today", "start_hour": 11, "end_hour": 16})
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (False, None)


def test_explicit_hourly_window_keeps_all_hours_when_now_is_before_it():
    facts = base_facts(now="2026-11-13T10:00")
    facts["hourly"].update(
        {
            "time": [f"2026-11-13T{hour:02}:00" for hour in range(24)],
            "uv_index": [9] * 24,
        }
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition("uv_index", "max", ">=", 8, {"day": "today", "start_hour": 11, "end_hour": 16})
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (True, 9)


def test_explicit_hourly_window_clips_hours_before_now_mid_window():
    facts = base_facts(now="2026-11-13T13:00")
    values = [0] * 24
    values[11], values[12], values[13], values[14], values[15], values[16] = 90, 80, 3, 4, 5, 6
    facts["hourly"].update(
        {"time": [f"2026-11-13T{hour:02}:00" for hour in range(24)], "uv_index": values}
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition("uv_index", "max", ">=", 6, {"day": "today", "start_hour": 11, "end_hour": 16})
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (True, 6)


def test_tomorrow_window_uses_full_target_date_window_after_time_shift():
    facts = base_facts(now="2026-11-14T00:00")
    times = [f"2026-11-15T{hour:02}:00" for hour in range(24)]
    values = [0] * 24
    values[11:17] = [4, 5, 6, 7, 8, 9]
    facts["hourly"].update({"time": times, "uv_index": values})
    condition = make_sop(
        all_conditions=[
            hourly_condition("uv_index", "max", ">=", 9, {"day": "tomorrow", "start_hour": 11, "end_hour": 16})
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (True, 9)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, True),
        ({"precipitation_probability": [30]}, False),
        ({"temperature_2m": [17]}, False),
        ({"temperature_2m_max_band": [33]}, False),
        ({"wind_gusts_10m": [25]}, False),
    ],
)
def test_picnic_numeric_bands(changes, expected):
    facts = base_facts()
    hourly = {
        "time": ["2026-11-13T12:00"],
        "precipitation_probability": [20],
        "temperature_2m": [20],
        "wind_gusts_10m": [20],
    }
    if "temperature_2m_max_band" in changes:
        hourly["temperature_2m"] = [changes["temperature_2m_max_band"][0]]
    else:
        hourly.update(changes)
    facts["hourly"] = hourly
    fixture_dir = Path(__file__).parent / "fixtures" / "sample_sops"
    sop = next(sop for sop in load_sops(fixture_dir) if sop.id == "picnic-good-001")

    assert sop_matches(sop, facts, now_from(facts))[0] is expected


def test_hourly_window_tomorrow_shifts_target_date():
    facts = base_facts(now="2026-11-13T10:00:00")
    facts["hourly"].update(
        {
            "time": ["2026-11-13T12:00", "2026-11-14T12:00"],
            "uv_index": [3, 9],
        }
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition(
                "uv_index", "max", ">=", 8, {"day": "tomorrow", "start_hour": 11, "end_hour": 13}
            )
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (True, 9)


def test_hourly_window_tomorrow_does_not_match_todays_value():
    facts = base_facts(now="2026-11-13T10:00:00")
    facts["hourly"].update(
        {
            "time": ["2026-11-13T12:00", "2026-11-14T12:00"],
            "uv_index": [9, 3],
        }
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition(
                "uv_index", "max", ">=", 8, {"day": "tomorrow", "start_hour": 11, "end_hour": 13}
            )
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (False, 3)


@pytest.mark.parametrize("threshold", [0, -100, 100])
def test_current_none_never_matches_greater_than_threshold(threshold):
    facts = base_facts()
    facts["current"]["temperature_2m"] = None
    condition = make_sop(all_conditions=[current_condition(value=threshold)]).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (False, None)


def test_hourly_all_none_in_window_does_not_match_or_raise():
    facts = base_facts()
    facts["hourly"].update(
        {"time": ["2026-11-13T11:00", "2026-11-13T12:00"], "uv_index": [None, None]}
    )
    condition = make_sop(
        all_conditions=[
            hourly_condition(
                "uv_index", "max", ">=", 8, {"day": "today", "start_hour": 11, "end_hour": 12}
            )
        ]
    ).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (False, None)


def test_empty_hourly_window_after_last_entry_does_not_raise():
    facts = base_facts(now="2026-11-13T18:00:00")
    facts["hourly"].update({"time": ["2026-11-13T16:00", "2026-11-13T17:00"], "uv_index": [8, 9]})
    condition = make_sop(all_conditions=[hourly_condition("uv_index", "max", ">=", 8)]).conditions.all[0]

    assert evaluate_condition(condition, facts, now_from(facts)) == (False, None)


def test_daily_condition_uses_today_or_tomorrow_index():
    facts = base_facts()
    facts["daily"] = {"time": ["2026-11-13", "2026-11-14"], "precipitation_sum": [0, 12]}
    sop = make_sop(
        all_conditions=[
            {"source": "daily", "field": "precipitation_sum", "day": "tomorrow", "op": ">", "value": 5}
        ]
    )

    assert sop_matches(sop, facts, now_from(facts))[0] is True


def test_none_activity_tag_only_allows_wildcard_sops():
    facts = base_facts()
    facts["current"]["temperature_2m"] = 20
    condition = [current_condition(value=0)]
    specific = make_sop(sop_id="specific", applies_to=["cycling"], all_conditions=condition)
    wildcard = make_sop(sop_id="wildcard", applies_to=["*"], all_conditions=condition)

    result = match_sops([specific, wildcard], facts, None, now_from(facts))

    assert [item.sop_id for item in result] == ["wildcard"]


def test_resolve_prefers_higher_severity_and_lists_other_match():
    high = MatchedSOP("high-sop", "exercise", "high", ["cycling"], "High", [])
    medium = MatchedSOP("medium-sop", "exercise", "medium", ["cycling"], "Medium", [])

    decision = resolve([medium, high])

    assert decision.primary.sop_id == "high-sop"
    assert decision.also_applies == ["medium-sop"]


def test_resolve_prefers_specific_over_wildcard_at_same_severity():
    wildcard = MatchedSOP("a-wildcard", "exercise", "medium", ["*"], "Wildcard", [])
    specific = MatchedSOP("z-specific", "exercise", "medium", ["cycling"], "Specific", [])

    decision = resolve([wildcard, specific])

    assert decision.primary.sop_id == "z-specific"
    assert decision.also_applies == ["a-wildcard"]


def test_resolve_uses_lower_id_for_same_severity_and_specificity():
    later = MatchedSOP("sop-b", "exercise", "low", ["cycling"], "Later", [])
    earlier = MatchedSOP("sop-a", "exercise", "low", ["cycling"], "Earlier", [])

    decision = resolve([later, earlier])

    assert decision.primary.sop_id == "sop-a"
    assert decision.also_applies == ["sop-b"]


def test_resolve_empty_list_returns_none():
    assert resolve([]) is None


def test_override_info_sop_precedes_matching_high_severity_sop():
    facts = base_facts()
    facts["current"]["temperature_2m"] = 20
    condition = [current_condition(value=0)]
    override_sop = make_sop(
        sop_id="override-info", severity="info", all_conditions=condition, override=True
    )
    high_sop = make_sop(sop_id="ordinary-high", severity="high", all_conditions=condition)

    matched = match_sops([high_sop, override_sop], facts, "cycling", now_from(facts))
    decision = resolve(matched)

    assert decision.primary.sop_id == "override-info"
    assert decision.primary.override is True
    assert decision.also_applies == ["ordinary-high"]


def test_override_wildcard_precedes_matching_specific_sop():
    facts = base_facts()
    facts["current"]["temperature_2m"] = 20
    condition = [current_condition(value=0)]
    override_wildcard = make_sop(
        sop_id="override-wildcard",
        severity="medium",
        applies_to=["*"],
        all_conditions=condition,
        override=True,
    )
    ordinary_specific = make_sop(
        sop_id="ordinary-specific",
        severity="medium",
        applies_to=["cycling"],
        all_conditions=condition,
    )

    matched = match_sops([ordinary_specific, override_wildcard], facts, "cycling", now_from(facts))
    decision = resolve(matched)

    assert decision.primary.sop_id == "override-wildcard"
    assert decision.also_applies == ["ordinary-specific"]


def test_higher_severity_override_precedes_lower_severity_override():
    facts = base_facts()
    facts["current"]["temperature_2m"] = 20
    condition = [current_condition(value=0)]
    info_override = make_sop(
        sop_id="override-info", severity="info", all_conditions=condition, override=True
    )
    high_override = make_sop(
        sop_id="override-high", severity="high", all_conditions=condition, override=True
    )

    matched = match_sops([info_override, high_override], facts, "cycling", now_from(facts))
    decision = resolve(matched)

    assert decision.primary.sop_id == "override-high"
    assert decision.primary.override is True
    assert decision.also_applies == ["override-info"]


def test_all_with_failure_does_not_match_and_any_with_true_does():
    facts = base_facts()
    facts["current"]["temperature_2m"] = 10
    all_sop = make_sop(
        sop_id="all-sop",
        all_conditions=[current_condition(value=0), current_condition(field="apparent_temperature", value=20)],
    )
    any_sop = make_sop(
        sop_id="any-sop",
        all_conditions=None,
        any_conditions=[current_condition(value=0), current_condition(field="apparent_temperature", value=20)],
    )

    all_match, all_triggers = sop_matches(all_sop, facts, now_from(facts))
    any_match, any_triggers = sop_matches(any_sop, facts, now_from(facts))

    assert all_match is False
    assert len(all_triggers) == 1
    assert any_match is True
    assert len(any_triggers) == 1
