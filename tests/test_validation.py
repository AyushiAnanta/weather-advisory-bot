from app.validation import allowed_numbers_for, extract_numbers, validate_reply


def decision(guidance="Wind guidance includes 40 km/h."):
    return {"primary": {"guidance": guidance, "trigger_values": []}, "also_applies": []}


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
