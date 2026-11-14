from collections import deque

from app.chat_service import ChatService
from app.sop_loader import load_sops, required_fields
from app.weather import GeoResult, WeatherResult


SOPS = load_sops("sops")
EXPECTED_KEYS = {
    "thread_id",
    "reply_body",
    "reply_kind",
    "sop",
    "also_applies",
    "trigger_values",
    "forecast",
    "failure_reason",
}


def facts_with_wind(gust_peak=10, now="2026-11-14T10:00"):
    fields = required_fields(SOPS)
    times = [f"2026-11-14T{hour:02}:00" for hour in range(24)]
    defaults = {
        "temperature_2m": 20,
        "apparent_temperature": 20,
        "precipitation_probability": 0,
        "precipitation": 0,
        "wind_speed_10m": 10,
        "wind_gusts_10m": 10,
        "uv_index": 0,
        "weather_code": 3,
        "pressure_msl": 1010,
    }
    hourly = {"time": times}
    for field in fields["hourly"]:
        hourly[field] = [defaults.get(field, 0)] * 24
    hourly["wind_gusts_10m"][15] = gust_peak
    daily = {"time": ["2026-11-14", "2026-11-15"]}
    for field in fields["daily"]:
        daily[field] = [0, 0]
    current = {field: 20 for field in fields["current"]}
    current.setdefault("temperature_2m", 20)
    return {
        "now": now,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 13.0,
        "grid_longitude": 80.0,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": current,
        "hourly": hourly,
        "daily": daily,
    }


def make_service(
    *,
    extractions=None,
    facts=None,
    geocode_result=None,
    weather_ok=True,
    classify_results=None,
    clock=lambda: 100.0,
):
    extraction_queue = deque(extractions or [{"city": "Sample Place", "activity_tag": "cycling"}])
    facts_queue = deque(facts or [facts_with_wind(45)])
    classify_queue = deque(classify_results or ["suitable"])
    calls = {"understand": 0, "geocode": [], "fetch": 0, "compose": 0, "classify": 0}
    location = geocode_result or GeoResult(
        ok=True,
        name="Sample Place",
        admin1="Sample Region",
        country="India",
        latitude=13,
        longitude=80,
        timezone="Asia/Kolkata",
        display="Sample Place, Sample Region, India",
    )

    def understand(_message, _tags, _summary):
        calls["understand"] += 1
        return extraction_queue.popleft() if extraction_queue else {"city": None, "activity_tag": None}

    def geocode(city):
        calls["geocode"].append(city)
        return location

    def fetch_weather(_lat, _lon, _fields):
        calls["fetch"] += 1
        if not weather_ok:
            return WeatherResult(ok=False, reason="weather_unavailable")
        return WeatherResult(ok=True, facts=facts_queue.popleft() if facts_queue else facts_with_wind(45))

    def compose(_compose_input):
        calls["compose"] += 1
        return "The forecast supports this advice."

    def classify(_classify_input):
        calls["classify"] += 1
        return classify_queue.popleft() if classify_queue else "suitable"

    deps = {
        "understand": understand,
        "compose": compose,
        "classify": classify,
        "geocode": geocode,
        "fetch_weather": fetch_weather,
    }
    return ChatService(deps, clock=clock), calls


def test_advice_response_has_structured_decision_and_no_citations_in_body():
    fake_facts = facts_with_wind(45)
    service, _calls = make_service(facts=[fake_facts])

    result = service.ask("thread-1", "Check the forecast.")

    assert set(result) == EXPECTED_KEYS
    assert result["reply_kind"] == "advice"
    assert "Policy:" not in result["reply_body"]
    assert result["sop"] == {
        "id": "wind-cycling-001",
        "severity": "high",
        "category": "exercise",
    }
    assert result["trigger_values"] == [
        {"field": "wind_gusts_10m", "agg": "max", "actual": 45}
    ]
    assert result["forecast"]["location"] == "Sample Place, Sample Region, India"
    assert result["forecast"]["as_of"] == fake_facts["now"]
    assert "facts" not in result


def test_no_match_response_has_no_sop():
    service, _calls = make_service(extractions=[{"city": "Sample Place", "activity_tag": "unknown_tag"}])

    result = service.ask("thread-1", "Check this activity.")

    assert result["reply_kind"] == "no_match"
    assert result["sop"] is None
    assert result["also_applies"] == []


def test_classifier_response_includes_sop_and_all_five_fact_values():
    facts = facts_with_wind(17)
    facts["hourly"]["precipitation_probability"] = [12] * 24
    facts["hourly"]["temperature_2m"] = [19 + (hour % 7) for hour in range(24)]
    facts["hourly"]["wind_gusts_10m"] = [8 + (hour % 10) for hour in range(24)]
    facts["hourly"]["uv_index"] = [hour % 9 for hour in range(24)]
    expected = {
        ("precipitation_probability", "max"): 12,
        ("temperature_2m", "min"): min(facts["hourly"]["temperature_2m"][10:]),
        ("temperature_2m", "max"): max(facts["hourly"]["temperature_2m"][10:]),
        ("wind_gusts_10m", "max"): max(facts["hourly"]["wind_gusts_10m"][10:]),
        ("uv_index", "max"): max(facts["hourly"]["uv_index"][10:]),
    }
    service, _calls = make_service(
        extractions=[{"city": "Sample Place", "activity_tag": "picnic"}],
        facts=[facts],
    )

    result = service.ask("picnic-thread", "Is a picnic comfortable?")

    assert result["reply_kind"] == "classifier"
    assert result["sop"] == {"id": "picnic-fuzzy-001", "severity": "info", "category": "leisure"}
    assert len(result["trigger_values"]) == 5
    assert {
        (item["field"], item["agg"]): item["actual"] for item in result["trigger_values"]
    } == expected


def test_classifier_retry_then_fail_returns_no_match_without_sop():
    service, _calls = make_service(
        extractions=[{"city": "Sample Place", "activity_tag": "picnic"}],
        classify_results=["excellent", "excellent"],
    )

    result = service.ask("picnic-thread", "Is a picnic comfortable?")

    assert result["reply_kind"] == "no_match"
    assert result["sop"] is None


def test_geocode_failure_returns_fallback_without_forecast():
    service, _calls = make_service(
        geocode_result=GeoResult(ok=False, reason="location_not_found")
    )

    result = service.ask("thread-1", "Check this place.")

    assert result["reply_kind"] == "fallback"
    assert result["failure_reason"] == "location_not_found"
    assert result["forecast"] is None


def test_session_reuses_location_and_other_threads_clarify():
    service, calls = make_service(
        extractions=[
            {"city": "Sample Place", "activity_tag": "cycling"},
            {"city": None, "activity_tag": None, "is_followup": True},
            {"city": None, "activity_tag": None},
        ],
        facts=[facts_with_wind(45), facts_with_wind(45)],
    )

    first = service.ask("same-thread", "Check cycling.")
    second = service.ask("same-thread", "What about later?")
    different_thread = service.ask("new-thread", "Check this too.")

    assert first["forecast"]["location"] == second["forecast"]["location"]
    assert calls["geocode"] == ["Sample Place"]
    assert calls["fetch"] == 2
    assert different_thread["reply_kind"] == "clarify"
    assert different_thread["forecast"] is None


def test_empty_message_guard_does_not_call_graph_deps():
    service, calls = make_service()

    result = service.ask("thread-1", "  ")

    assert result["reply_kind"] == "rejected"
    assert result["failure_reason"] == "empty_message"
    assert calls["understand"] == 0


def test_too_long_message_guard_does_not_call_graph_deps(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_CHARS", "3")
    service, calls = make_service()

    result = service.ask("thread-1", "long")

    assert result["reply_kind"] == "rejected"
    assert result["failure_reason"] == "message_too_long"
    assert calls["understand"] == 0


def test_disabled_guard_does_not_call_graph_deps(monkeypatch):
    monkeypatch.setenv("CHAT_DISABLED", "1")
    service, calls = make_service()

    result = service.ask("thread-1", "Check this.")

    assert result["reply_kind"] == "rejected"
    assert result["failure_reason"] == "chat_disabled"
    assert calls["understand"] == 0


def test_session_turn_limit_rejects_twenty_first_without_graph_call(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_TURNS_PER_SESSION", "20")
    monkeypatch.setenv("CHAT_MAX_PER_DAY", "500")
    service, calls = make_service()

    for _ in range(20):
        service.ask("thread-1", "Check this.")
    calls_after_twenty = calls["understand"]
    result = service.ask("thread-1", "One more.")

    assert result["reply_kind"] == "rejected"
    assert result["failure_reason"] == "session_limit"
    assert calls["understand"] == calls_after_twenty == 20


def test_daily_limit_rejects_without_graph_and_expires_after_24_hours(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_PER_DAY", "1")
    clock_value = [100.0]
    service, calls = make_service(
        extractions=[
            {"city": "Sample Place", "activity_tag": "cycling"},
            {"city": "Sample Place", "activity_tag": "cycling"},
        ],
        clock=lambda: clock_value[0],
    )

    service.ask("thread-1", "First message.")
    calls_after_first = calls["understand"]
    rejected = service.ask("thread-2", "Second message.")
    calls_after_rejection = calls["understand"]
    clock_value[0] += 24 * 60 * 60
    allowed = service.ask("thread-2", "A day later.")

    assert rejected["reply_kind"] == "rejected"
    assert rejected["failure_reason"] == "daily_limit"
    assert calls_after_rejection == calls_after_first == 1
    assert allowed["reply_kind"] == "advice"
    assert calls["understand"] == 2


def test_unexpected_graph_exception_is_logged_without_user_traceback(capsys):
    service, _calls = make_service()

    class BrokenGraph:
        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("private failure detail")

    service.graph = BrokenGraph()
    result = service.ask("thread-1", "Check this.")
    error_output = capsys.readouterr().err

    assert result["reply_kind"] == "error"
    assert "private failure detail" not in result["reply_body"]
    assert "private failure detail" in error_output
    assert "Traceback" not in error_output
