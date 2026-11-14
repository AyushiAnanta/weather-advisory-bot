from datetime import datetime

import pytest

from app.matcher import match_sops, resolve
from app.sop_loader import load_sops


EXERCISE_ID = "heat-humidity-exercise-001"
ELDERLY_ID = "elderly-heat-001"


def facts_with_apparent_temperatures(values):
    return {
        "now": "2026-11-13T12:00:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {
            "time": [
                "2026-11-13T11:00",
                "2026-11-13T12:00",
                "2026-11-13T13:00",
                "2026-11-13T14:00",
                "2026-11-13T15:00",
                "2026-11-13T16:00",
            ],
            "apparent_temperature": values,
        },
        "daily": {"time": []},
    }


def matching_for(facts, activity_tag):
    sops = load_sops("sops")
    now = datetime.fromisoformat(facts["now"])
    matched = match_sops(sops, facts, activity_tag, now)
    return {item.sop_id for item in matched}, resolve(matched)


def test_outdoor_exercise_activity_matches_only_exercise_heat_sop():
    facts = facts_with_apparent_temperatures([31, 36, 33, 32, 30, 29])

    matched_ids, decision = matching_for(facts, "outdoor_exercise")

    assert EXERCISE_ID in matched_ids
    assert ELDERLY_ID not in matched_ids
    assert decision.primary.sop_id == EXERCISE_ID


def test_elderly_activity_matches_only_elderly_heat_sop_at_36():
    facts = facts_with_apparent_temperatures([31, 36, 33, 32, 30, 29])

    matched_ids, decision = matching_for(facts, "elderly")

    assert ELDERLY_ID in matched_ids
    assert EXERCISE_ID not in matched_ids
    assert decision.primary.sop_id == ELDERLY_ID


def test_elderly_threshold_matches_at_33_while_exercise_does_not():
    facts = facts_with_apparent_temperatures([31, 33, 32, 30, 29, 28])

    matched_ids, decision = matching_for(facts, "elderly")

    assert ELDERLY_ID in matched_ids
    assert EXERCISE_ID not in matched_ids
    assert decision.primary.sop_id == ELDERLY_ID


@pytest.mark.parametrize("activity_tag", ["elderly", "outdoor_exercise"])
def test_max_30_matches_neither_heat_sop(activity_tag):
    facts = facts_with_apparent_temperatures([29, 30, 28, 27, 26, 25])

    matched_ids, decision = matching_for(facts, activity_tag)

    assert EXERCISE_ID not in matched_ids
    assert ELDERLY_ID not in matched_ids
    assert decision is None


def test_full_sop_directory_loads_with_both_stage4_ids():
    sops = load_sops("sops")
    ids = [sop.id for sop in sops]

    assert EXERCISE_ID in ids
    assert ELDERLY_ID in ids


COLD_JOG_ID = "cold-morning-jog-001"
TRAVEL_PRECIPITATION_ID = "high-precipitation-probability-travel-001"


def facts_for_cold_window(minimum_temperature):
    return {
        "now": "2026-11-13T06:00:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {
            "time": [
                "2026-11-13T05:00",
                "2026-11-13T06:00",
                "2026-11-13T07:00",
                "2026-11-13T08:00",
            ],
            "temperature_2m": [12, minimum_temperature, 12, 13],
        },
        "daily": {"time": []},
    }


def facts_for_travel_precipitation(maximum_probability):
    times = [f"2026-11-13T{hour:02}:00" for hour in range(24)]
    probabilities = [20] * 24
    probabilities[14] = maximum_probability
    return {
        "now": "2026-11-13T12:00:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {"time": times, "precipitation_probability": probabilities},
        "daily": {"time": []},
    }


def test_cold_morning_jog_matches_outdoor_exercise_and_running():
    facts = facts_for_cold_window(10)

    for activity_tag in ("outdoor_exercise", "running"):
        matched_ids, decision = matching_for(facts, activity_tag)
        assert matched_ids == {COLD_JOG_ID}
        assert decision.primary.sop_id == COLD_JOG_ID


def test_cold_morning_jog_does_not_match_at_11_degrees():
    facts = facts_for_cold_window(11)

    matched_ids, decision = matching_for(facts, "outdoor_exercise")

    assert COLD_JOG_ID not in matched_ids
    assert decision is None


def test_high_precipitation_probability_matches_travel_at_70():
    facts = facts_for_travel_precipitation(70)

    matched_ids, decision = matching_for(facts, "travel")

    assert matched_ids == {TRAVEL_PRECIPITATION_ID}
    assert decision.primary.sop_id == TRAVEL_PRECIPITATION_ID


def test_high_precipitation_probability_does_not_match_at_69():
    facts = facts_for_travel_precipitation(69)

    matched_ids, decision = matching_for(facts, "travel")

    assert TRAVEL_PRECIPITATION_ID not in matched_ids
    assert decision is None


def test_cycling_does_not_match_either_new_sop_when_conditions_match():
    facts = facts_for_travel_precipitation(70)
    temperatures = [20] * 24
    temperatures[6] = 10
    facts["hourly"]["temperature_2m"] = temperatures

    matched_ids, _ = matching_for(facts, "cycling")

    assert COLD_JOG_ID not in matched_ids
    assert TRAVEL_PRECIPITATION_ID not in matched_ids


def test_full_sop_directory_loads_nine_unique_sops_after_stage4():
    sops = load_sops("sops")
    ids = [sop.id for sop in sops]

    assert len(sops) == 9
    assert len(ids) == len(set(ids))
    assert {
        "wind-cycling-001",
        "uv-exercise-001",
        "picnic-good-001",
        EXERCISE_ID,
        ELDERLY_ID,
        COLD_JOG_ID,
        TRAVEL_PRECIPITATION_ID,
        "thunderstorm-proxy-001",
        "compound-severe-weather-001",
    } <= set(ids)


THUNDERSTORM_ID = "thunderstorm-proxy-001"


def facts_for_weather_codes(codes):
    times = [f"2026-11-13T{hour:02}:00" for hour in range(11, 11 + len(codes))]
    return {
        "now": "2026-11-13T12:00:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {"time": times, "weather_code": codes},
        "daily": {"time": []},
    }


def test_thunderstorm_wildcard_matches_arbitrary_activity():
    facts = facts_for_weather_codes([3, 95, 1])

    matched_ids, decision = matching_for(facts, "cycling")

    assert THUNDERSTORM_ID in matched_ids
    assert decision.primary.sop_id == THUNDERSTORM_ID


def test_thunderstorm_sop_does_not_match_without_storm_code():
    facts = facts_for_weather_codes([0, 1, 2, 3])

    matched_ids, decision = matching_for(facts, "cycling")

    assert THUNDERSTORM_ID not in matched_ids
    assert decision is None


def test_thunderstorm_trigger_reports_max_code_95():
    facts = facts_for_weather_codes([3, 95])

    matched = match_sops(load_sops("sops"), facts, "picnic", datetime.fromisoformat(facts["now"]))
    thunderstorm_match = next(item for item in matched if item.sop_id == THUNDERSTORM_ID)

    assert thunderstorm_match.trigger_values[0]["actual"] == 95


def test_full_sop_directory_loads_nine_unique_sops():
    sops = load_sops("sops")
    ids = [sop.id for sop in sops]

    assert len(sops) == 9
    assert len(ids) == len(set(ids))
    assert THUNDERSTORM_ID in ids
    assert COMPOUND_ID in ids


COMPOUND_ID = "compound-severe-weather-001"


def facts_for_compound_severe_weather(precipitation_sum, gust_peak):
    times = [f"2026-11-13T{hour:02}:00" for hour in range(24)]
    gusts = [10] * 24
    gusts[12] = gust_peak
    return {
        "now": "2026-11-13T12:00",
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": {},
        "hourly": {"time": times, "wind_gusts_10m": gusts},
        "daily": {"time": ["2026-11-13"], "precipitation_sum": [precipitation_sum]},
    }


def test_compound_severe_weather_matches_and_reports_both_actual_values():
    facts = facts_for_compound_severe_weather(65.0, 45)

    matched = match_sops(load_sops("sops"), facts, "cycling", datetime.fromisoformat(facts["now"]))
    compound = next(item for item in matched if item.sop_id == COMPOUND_ID)

    assert [trigger["actual"] for trigger in compound.trigger_values] == [65.0, 45]


@pytest.mark.parametrize(
    ("precipitation_sum", "gust_peak", "expected"),
    [(65.0, 40, True), (64.9, 45, False), (70, 39.9, False)],
)
def test_compound_severe_weather_boundaries(precipitation_sum, gust_peak, expected):
    facts = facts_for_compound_severe_weather(precipitation_sum, gust_peak)

    matched_ids, _ = matching_for(facts, "cycling")

    assert (COMPOUND_ID in matched_ids) is expected


def test_compound_severe_weather_requires_both_precipitation_and_gusts():
    facts = facts_for_compound_severe_weather(70, 30)

    matched_ids, _ = matching_for(facts, "cycling")

    assert COMPOUND_ID not in matched_ids


def test_compound_severe_weather_does_not_match_with_low_precipitation():
    facts = facts_for_compound_severe_weather(10, 45)

    matched_ids, _ = matching_for(facts, "cycling")

    assert COMPOUND_ID not in matched_ids


def test_compound_override_precedes_matching_wind_cycling_sop():
    facts = facts_for_compound_severe_weather(70, 45)

    matched_ids, decision = matching_for(facts, "cycling")

    assert COMPOUND_ID in matched_ids
    assert "wind-cycling-001" in matched_ids
    assert decision.primary.sop_id == COMPOUND_ID
    assert "wind-cycling-001" in decision.also_applies


def test_compound_wildcard_matches_and_resolves_for_picnic():
    facts = facts_for_compound_severe_weather(70, 45)

    matched_ids, decision = matching_for(facts, "picnic")

    assert COMPOUND_ID in matched_ids
    assert decision.primary.sop_id == COMPOUND_ID


def test_compound_severe_weather_missing_precipitation_does_not_match():
    facts = facts_for_compound_severe_weather(None, 45)

    matched_ids, decision = matching_for(facts, "picnic")

    assert COMPOUND_ID not in matched_ids
    assert decision is None
