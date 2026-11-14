from datetime import datetime

from app.matcher import match_sops, resolve, sop_matches
from app.sop_loader import SOP, load_sops


CHILD_UV_ID = "child-uv-001"
PET_HEAT_ID = "pet-heat-001"
NOW = "2026-11-13T12:00"


def facts_for_hourly_values(field, values_by_hour, now=NOW):
    values = [20] * 24
    if field == "uv_index":
        values = [0] * 24
    for hour, value in values_by_hour.items():
        values[hour] = value
    return {
        "now": now,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {
            "time": [f"2026-11-13T{hour:02}:00" for hour in range(24)],
            field: values,
        },
        "daily": {"time": ["2026-11-13"]},
    }


def matching_for(facts, activity_tag):
    return match_sops(
        load_sops("sops"),
        facts,
        activity_tag,
        datetime.fromisoformat(facts["now"]),
    )


def facts_for_uv_and_wind(uv=9, gust=20):
    times = [f"2026-11-13T{hour:02}:00" for hour in range(24)]
    times += [f"2026-11-14T{hour:02}:00" for hour in range(24)]
    hourly = {
        "time": times,
        "apparent_temperature": [24.0] * 48,
        "precipitation_probability": [5] * 48,
        "temperature_2m": [24.0] * 48,
        "uv_index": [uv if 11 <= index % 24 <= 16 and index < 24 else 2 for index in range(48)],
        "weather_code": [3] * 48,
        "wind_gusts_10m": [gust if index == 15 else 10 for index in range(48)],
    }
    return {
        "now": "2026-11-13T12:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": hourly,
        "daily": {"time": ["2026-11-13", "2026-11-14"], "precipitation_sum": [0, 0]},
    }


def test_uv_policy_applies_to_running():
    matched = matching_for(facts_for_uv_and_wind(), "running")

    assert any(item.sop_id == "uv-exercise-001" for item in matched)


def test_wind_policy_precedes_uv_for_cycling_when_both_match():
    matched = matching_for(facts_for_uv_and_wind(uv=9, gust=45), "cycling")
    decision = resolve(matched)

    assert decision.primary.sop_id == "wind-cycling-001"
    assert "uv-exercise-001" in decision.also_applies


def test_uv_policy_is_primary_for_cycling_when_wind_does_not_match():
    matched = matching_for(facts_for_uv_and_wind(uv=9, gust=20), "cycling")
    decision = resolve(matched)

    assert decision.primary.sop_id == "uv-exercise-001"


def test_uv_policy_does_not_apply_to_picnic():
    matched = matching_for(facts_for_uv_and_wind(uv=9), "picnic")

    assert all(item.sop_id != "uv-exercise-001" for item in matched)


def test_child_uv_matches_threshold_and_reports_max():
    facts = facts_for_hourly_values("uv_index", {14: 6.0})

    matched = matching_for(facts, "child_outdoor_play")
    child_match = next(item for item in matched if item.sop_id == CHILD_UV_ID)

    assert child_match.trigger_values[0]["actual"] == 6.0


def test_child_uv_does_not_match_below_threshold():
    facts = facts_for_hourly_values("uv_index", {14: 5.9})

    matched = matching_for(facts, "child_outdoor_play")

    assert all(item.sop_id != CHILD_UV_ID for item in matched)


def test_child_uv_does_not_match_when_high_uv_is_before_now():
    facts = facts_for_hourly_values("uv_index", {8: 9})

    matched = matching_for(facts, "child_outdoor_play")

    assert all(item.sop_id != CHILD_UV_ID for item in matched)


def test_child_uv_requires_child_activity_tag():
    facts = facts_for_hourly_values("uv_index", {14: 9})

    matched = matching_for(facts, "cycling")

    assert all(item.sop_id != CHILD_UV_ID for item in matched)


def test_child_uv_counts_current_hour_at_half_past():
    facts = facts_for_hourly_values("uv_index", {12: 9}, now="2026-11-13T12:30")

    matched = matching_for(facts, "child_outdoor_play")

    assert any(item.sop_id == CHILD_UV_ID for item in matched)


def test_pet_heat_matches_threshold_and_reports_max():
    facts = facts_for_hourly_values("temperature_2m", {15: 35.0})

    matched = matching_for(facts, "pet_walk")
    pet_match = next(item for item in matched if item.sop_id == PET_HEAT_ID)

    assert pet_match.trigger_values[0]["actual"] == 35.0


def test_pet_heat_does_not_match_below_threshold():
    facts = facts_for_hourly_values("temperature_2m", {15: 34.9})

    matched = matching_for(facts, "pet_walk")

    assert all(item.sop_id != PET_HEAT_ID for item in matched)


def test_pet_heat_does_not_match_when_peak_is_before_now():
    facts = facts_for_hourly_values("temperature_2m", {9: 38})

    matched = matching_for(facts, "pet_walk")

    assert all(item.sop_id != PET_HEAT_ID for item in matched)


def test_pet_heat_requires_pet_walk_activity_tag():
    facts = facts_for_hourly_values("temperature_2m", {15: 38})

    matched = matching_for(facts, "cycling")

    assert all(item.sop_id != PET_HEAT_ID for item in matched)


def test_known_limitation_in_applies_to_aggregate_not_each_hour():
    """in is applied to the window aggregate, not to each hour, so a lower-ranked code hidden by a higher one is missed"""
    sop = SOP.model_validate(
        {
            "id": "fog-limitation-test",
            "category": "travel",
            "severity": "medium",
            "applies_to": ["travel"],
            "conditions": {
                "all": [
                    {
                        "source": "hourly",
                        "field": "weather_code",
                        "agg": "max",
                        "op": "in",
                        "value": [45, 48],
                    }
                ]
            },
            "guidance": "Test condition.",
        }
    )
    facts = facts_for_hourly_values("weather_code", {14: 45, 15: 51})

    matched, _ = sop_matches(sop, facts, datetime.fromisoformat(facts["now"]))

    assert matched is False
