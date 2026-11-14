import json
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from app.graph import ComposeInput, build_graph
from app.matcher import resolve
from app.sop_loader import load_sops, required_fields
from app.stubs import stub_compose
from app.weather import GeoResult, WeatherResult


SOPS = load_sops("sops")
SOP_IDS = {sop.id for sop in SOPS}
NOW = "2026-11-13T12:00"


def facts_with(hourly_overrides=None, daily_overrides=None, now=NOW):
    fields = required_fields(SOPS)
    hourly_times = [f"2026-11-13T{hour:02}:00" for hour in range(24)]
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
    hourly = {"time": hourly_times}
    for field in fields["hourly"]:
        hourly[field] = [defaults.get(field, 0)] * len(hourly_times)
    for field, values_by_hour in (hourly_overrides or {}).items():
        for hour, value in values_by_hour.items():
            hourly[field][hour] = value

    daily = {"time": ["2026-11-13", "2026-11-14"]}
    for field in fields["daily"]:
        daily[field] = [0, 0]
    for field, values in (daily_overrides or {}).items():
        daily[field] = values

    current = {field: 20 for field in fields["current"]}
    current.setdefault("temperature_2m", 20)
    return {
        "now": now,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "grid_latitude": 12.3,
        "grid_longitude": 45.6,
        "units": {"current": {}, "hourly": {}, "daily": {}},
        "current": current,
        "hourly": hourly,
        "daily": daily,
    }


def extraction(city="Sample Place", activity="cycling", time_ref=None, is_followup=False):
    return {
        "city": city,
        "activity_tag": activity,
        "time_ref": time_ref,
        "is_followup": is_followup,
    }


def make_deps(
    extractions=None,
    fact_results=None,
    geocode_result=None,
    weather_ok=True,
    compose_fn=None,
    classify_results=None,
):
    extractions = list(extractions or [extraction()])
    fact_results = list(fact_results or [facts_with()])
    classify_results = list(classify_results or ["suitable"])
    calls = {"understand": [], "geocode": [], "fetch": [], "compose": [], "classify": []}
    location = geocode_result or GeoResult(
        ok=True,
        name="Sample Place",
        admin1="Sample Region",
        country="India",
        latitude=13.0,
        longitude=80.0,
        timezone="Asia/Kolkata",
        display="Sample Place, Sample Region, India",
    )

    def understand(message, allowed_tags, session_summary):
        calls["understand"].append((message, allowed_tags, session_summary))
        return extractions.pop(0) if extractions else extraction(city=None, activity=None)

    def geocode(city):
        calls["geocode"].append(city)
        return location

    def fetch_weather(lat, lon, requested_fields):
        calls["fetch"].append((lat, lon, requested_fields))
        if not weather_ok:
            return WeatherResult(ok=False, reason="weather_unavailable")
        next_facts = fact_results.pop(0) if fact_results else facts_with()
        return WeatherResult(ok=True, facts=next_facts)

    def compose(compose_input):
        calls["compose"].append(compose_input)
        return compose_fn(compose_input) if compose_fn else stub_compose(compose_input)

    def classify(classify_input):
        calls["classify"].append(classify_input)
        return classify_results.pop(0) if classify_results else "suitable"

    return {
        "geocode": geocode,
        "fetch_weather": fetch_weather,
        "understand": understand,
        "compose": compose,
        "classify": classify,
    }, calls


def invoke(graph, thread="one", message="Please check the forecast."):
    return graph.invoke(
        {"user_message": message},
        config={"configurable": {"thread_id": thread}},
    )


def test_graph_success_composes_and_cites_matching_wind_policy():
    facts = facts_with({"wind_gusts_10m": {15: 45}})
    deps, calls = make_deps(fact_results=[facts])
    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "advice"
    assert result["cited_sop_ids"][0] == "wind-cycling-001"
    assert f"Policy: {result['cited_sop_ids'][0]}" in result["reply"]
    assert len(calls["compose"]) == 1
    json.dumps(result)


def test_geocode_failure_falls_back_without_fetch_or_compose():
    deps, calls = make_deps(geocode_result=GeoResult(ok=False, reason="geocoding_unavailable"))

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "fallback"
    assert calls["fetch"] == []
    assert calls["compose"] == []


def test_weather_failure_falls_back_without_compose():
    deps, calls = make_deps(weather_ok=False)

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "fallback"
    assert calls["compose"] == []


def test_no_matching_policy_uses_fixed_no_match_without_llm():
    deps, calls = make_deps(extractions=[extraction(activity="unlisted_activity")])

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "no_match"
    assert calls["compose"] == []
    assert calls["classify"] == []


def test_picnic_routes_to_classifier_and_cites_its_outcome():
    deps, calls = make_deps(extractions=[extraction(activity="picnic")], classify_results=["suitable"])

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "classifier"
    assert result["reply"].startswith("Conditions look comfortable for a picnic today.")
    assert result["cited_sop_ids"] == ["picnic-fuzzy-001"]
    assert len(calls["classify"]) == 1
    assert "facts" in calls["classify"][0] and "rubric" in calls["classify"][0]


def test_invalid_classifier_label_twice_routes_to_no_match():
    deps, calls = make_deps(
        extractions=[extraction(activity="picnic")], classify_results=["excellent", "excellent"]
    )

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "no_match"
    assert len(calls["classify"]) == 2


def test_invalid_classifier_label_retries_then_succeeds():
    deps, calls = make_deps(
        extractions=[extraction(activity="picnic")], classify_results=["excellent", "marginal"]
    )

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "classifier"
    assert result["reply"].startswith("Conditions are mixed for a picnic today.")
    assert len(calls["classify"]) == 2


def test_override_policy_wins_and_lists_wind_policy():
    facts = facts_with(
        {"wind_gusts_10m": {15: 45}},
        {"precipitation_sum": [70, 0]},
    )
    deps, _ = make_deps(fact_results=[facts])

    result = invoke(build_graph(SOPS, deps))

    assert result["cited_sop_ids"][0] == "compound-severe-weather-001"
    assert "Also applies: wind-cycling-001" in result["reply"]


def test_unsupported_compose_number_uses_deterministic_template():
    facts = facts_with({"wind_gusts_10m": {15: 45}})
    deps, _ = make_deps(fact_results=[facts], compose_fn=lambda _input: "It may reach 99 km/h.")

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "template"
    assert "99" not in result["reply"]


def test_unknown_sop_citation_uses_deterministic_template():
    facts = facts_with({"wind_gusts_10m": {15: 45}})
    deps, _ = make_deps(
        fact_results=[facts], compose_fn=lambda _input: "See unsupported-policy-999 for details."
    )

    result = invoke(build_graph(SOPS, deps))

    assert result["reply_kind"] == "template"
    assert "unsupported-policy-999" not in result["reply"]


def test_raw_user_marker_is_excluded_from_compose_input():
    facts = facts_with({"wind_gusts_10m": {15: 45}})
    deps, calls = make_deps(fact_results=[facts])

    invoke(build_graph(SOPS, deps), message="ZZZ-MARKER-123 check this forecast")
    compose_input = calls["compose"][0]
    field_names = {field.name for field in dataclass_fields(ComposeInput)}

    assert "ZZZ-MARKER-123" not in repr(compose_input)
    assert not any("message" in name or "history" in name for name in field_names)


def test_session_reuses_location_activity_and_previous_decision():
    facts = facts_with({"wind_gusts_10m": {15: 45}})
    deps, calls = make_deps(
        extractions=[extraction(), extraction(city=None, activity=None, is_followup=True)],
        fact_results=[facts, facts],
    )
    graph = build_graph(SOPS, deps, checkpointer=MemorySaver())

    first = invoke(graph, thread="same-thread")
    second = invoke(graph, thread="same-thread", message="And later?")

    assert first["reply_kind"] == second["reply_kind"] == "advice"
    assert len(calls["geocode"]) == 1
    assert len(calls["fetch"]) == 2
    assert calls["compose"][1].previous_decision.sop_id == first["cited_sop_ids"][0]
    assert "Sample Place, Sample Region, India" in second["reply"]


def test_new_thread_without_city_clarifies():
    deps, calls = make_deps(extractions=[extraction(city=None, activity=None)])
    graph = build_graph(SOPS, deps, checkpointer=MemorySaver())

    result = invoke(graph, thread="different-thread")

    assert result["reply_kind"] == "clarify"
    assert calls["geocode"] == []


def test_city_and_activity_context_inherit_independently():
    facts_cycle = facts_with({"wind_gusts_10m": {15: 45}})
    facts_pet = facts_with({"temperature_2m": {15: 35}})
    deps, calls = make_deps(
        extractions=[
            extraction(city="First Sample", activity="cycling"),
            extraction(city="Second Sample", activity=None),
            extraction(city=None, activity="pet_walk"),
        ],
        fact_results=[facts_cycle, facts_cycle, facts_pet],
    )
    graph = build_graph(SOPS, deps, checkpointer=MemorySaver())

    first = invoke(graph, thread="inherit-thread")
    second = invoke(graph, thread="inherit-thread")
    third = invoke(graph, thread="inherit-thread")

    assert first["cited_sop_ids"][0] == "wind-cycling-001"
    assert second["cited_sop_ids"][0] == "wind-cycling-001"
    assert third["cited_sop_ids"][0] == "pet-heat-001"
    assert calls["geocode"] == ["First Sample", "Second Sample"]
    assert "Sample Place, Sample Region, India" in third["reply"]


def test_compiled_graph_topology_and_mermaid_document_exist():
    deps, _ = make_deps()
    graph = build_graph(SOPS, deps)
    required_nodes = {
        "begin_turn", "understand", "merge_context", "clarify", "geocode",
        "fetch_weather", "fallback", "match_sops", "resolve", "classify",
        "no_match", "compose", "validate", "finalize",
    }

    assert required_nodes <= set(graph.get_graph().nodes)
    mermaid = Path("docs/graph.md").read_text(encoding="utf-8")
    assert "```mermaid" in mermaid


def test_app_contains_no_system_clock_calls():
    app_dir = Path(__file__).parents[1] / "app"
    banned = ("datetime.now", "utcnow", "time.time(")

    assert not [
        (path.name, text)
        for path in app_dir.glob("*.py")
        for text in banned
        if text in path.read_text(encoding="utf-8")
    ]
