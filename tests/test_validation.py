from app.validation import allowed_numbers_for, extract_numbers, validate_reply


def decision(guidance="Wind guidance includes 40 km/h.", sop_id=None, also_applies=None):
    primary = {"guidance": guidance, "trigger_values": []}
    if sop_id is not None:
        primary["sop_id"] = sop_id
    return {"primary": primary, "also_applies": also_applies or []}


def test_invented_number_fails_validation():
    assert validate_reply("Wind may reach 99 km/h.", {45.0}, ["wind-cycling-001"])[0] is False


def test_number_from_trigger_values_passes():
    assert validate_reply("The measured gust was 45.", {45.0}, ["wind-cycling-001"])[0] is True


def test_number_from_sop_guidance_passes():
    allowed = allowed_numbers_for(decision(), [], "Sample, Region, India")

    assert allowed == {40.0}
    assert validate_reply("Wind guidance includes 40 km/h.", allowed, [])[0] is True


def test_unknown_sop_id_fails_validation():
    ok, reasons = validate_reply("See policy fake-rule-999.", set(), ["wind-cycling-001"])

    assert ok is False
    assert any("fake-rule-999" in reason for reason in reasons)


def test_matched_sop_id_digits_do_not_count_as_reply_numbers():
    assert validate_reply("Policy wind-cycling-001 applies.", set(), ["wind-cycling-001"])[0] is True
    assert validate_reply("Policy policy-42 applies.", set(), ["policy-42"])[0] is True


def test_integer_and_decimal_values_compare_numerically():
    assert validate_reply("The value was 45.0.", {45.0}, [])[0] is True


def test_reply_without_numbers_passes():
    assert validate_reply("Conditions look comfortable.", set(), [])[0] is True


def test_cited_wind_policy_threshold_and_decimal_actual_are_allowed():
    selected = decision(guidance="Wind guidance.", sop_id="wind-cycling-001")
    actuals = [{"field": "wind_gusts_10m", "agg": "max", "actual": 43.9}]
    allowed = allowed_numbers_for(selected, actuals, "Sample, Region, India")

    reply = "Wind gusts are 43.9, which meets the threshold of 40."
    assert {40.0, 43.9} <= allowed
    assert validate_reply(reply, allowed, ["wind-cycling-001"]) == (True, [])


def test_uncited_wind_threshold_is_not_allowed_for_matched_heat_policy():
    selected = decision(guidance="Heat guidance.", sop_id="heat-humidity-exercise-001")
    actuals = [{"field": "apparent_temperature", "agg": "max", "actual": 36.2}]
    allowed = allowed_numbers_for(selected, actuals, "Sample, Region, India")

    ok, reasons = validate_reply(
        "Wind gusts are 36.2, which meets the threshold of 40.",
        allowed,
        ["heat-humidity-exercise-001"],
    )

    assert 35.0 in allowed
    assert 36.2 in allowed
    assert 40.0 not in allowed
    assert ok is False
    assert "reply contains unsupported number: 40" in reasons


def test_nearby_unlisted_number_still_fails():
    selected = decision(guidance="Wind guidance.", sop_id="wind-cycling-001")
    allowed = allowed_numbers_for(
        selected,
        [{"field": "wind_gusts_10m", "agg": "max", "actual": 43.9}],
        "Sample, Region, India",
    )

    ok, reasons = validate_reply(
        "Wind gusts are 41.",
        allowed,
        ["wind-cycling-001"],
    )

    assert ok is False
    assert "reply contains unsupported number: 41" in reasons


def test_rounded_actual_still_fails_exact_number_check():
    selected = decision(guidance="Wind guidance.", sop_id="wind-cycling-001")
    allowed = allowed_numbers_for(
        selected,
        [{"field": "wind_gusts_10m", "agg": "max", "actual": 43.9}],
        "Sample, Region, India",
    )

    ok, reasons = validate_reply(
        "Wind gusts are 44.",
        allowed,
        ["wind-cycling-001"],
    )

    assert ok is False
    assert "reply contains unsupported number: 44" in reasons


def test_each_cited_list_condition_value_is_allowed():
    selected = decision(guidance="Storm guidance.", sop_id="thunderstorm-proxy-001")
    allowed = allowed_numbers_for(selected, [], "Sample, Region, India")

    for value in (95, 96, 99):
        assert validate_reply(
            f"Forecast weather code {value} is in the storm set.",
            allowed,
            ["thunderstorm-proxy-001"],
        ) == (True, [])


def test_template_uses_primary_guidance_location_and_trigger_values():
    from app.validation import build_template_reply

    value = decision("Use care above 40.")
    value["primary"]["sop_id"] = "wind-cycling-001"
    value["primary"]["severity"] = "high"
    value["primary"]["trigger_values"] = [
        {"field": "wind_gusts_10m", "agg": "max", "actual": 45}
    ]

    reply = build_template_reply(value, "Sample, Region, India")

    assert reply == "Sample, Region, India: Use care above 40. Forecast facts: wind_gusts_10m max was 45."
