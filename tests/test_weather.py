from unittest.mock import Mock

import pytest
import requests

import app.weather as weather


class FakeResponse:
    def __init__(self, status_code=200, body=None, json_error=None):
        self.status_code = status_code
        self.body = body
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.body


def patch_get(monkeypatch, response=None, side_effect=None):
    get = Mock(return_value=response, side_effect=side_effect)
    monkeypatch.setattr(weather.requests, "get", get)
    return get


def assert_geocode_call(get, name):
    get.assert_called_once_with(
        weather.GEOCODING_URL,
        params={"name": name, "count": 10, "countryCode": "IN"},
        timeout=10,
    )


def test_geocode_nonsense_city_without_results_key(monkeypatch):
    get = patch_get(monkeypatch, FakeResponse(body={"generationtime_ms": 0.1}))
    result = weather.geocode("nonsense city")
    assert result.ok is False
    assert result.reason == "location_not_found"
    assert_geocode_call(get, "nonsense city")


def test_geocode_empty_results(monkeypatch):
    get = patch_get(monkeypatch, FakeResponse(body={"results": []}))
    result = weather.geocode("No Such Place")
    assert result.ok is False
    assert result.reason == "location_not_found"
    assert_geocode_call(get, "No Such Place")


def test_geocode_results_without_indian_entry(monkeypatch):
    get = patch_get(
        monkeypatch,
        FakeResponse(body={"results": [{"name": "Paris", "country_code": "FR"}]}),
    )
    result = weather.geocode("Paris")
    assert result.ok is False
    assert result.reason == "location_not_found"
    assert_geocode_call(get, "Paris")


def test_geocode_skips_non_indian_first_result(monkeypatch):
    get = patch_get(
        monkeypatch,
        FakeResponse(
            body={
                "results": [
                    {"name": "Springfield", "country_code": "US", "latitude": 1, "longitude": 2},
                    {
                        "name": "Springfield",
                        "admin1": "Maharashtra",
                        "country": "India",
                        "country_code": "IN",
                        "latitude": 19.076,
                        "longitude": 72.878,
                        "timezone": "Asia/Kolkata",
                    },
                ]
            }
        ),
    )
    result = weather.geocode("Springfield")
    assert result.ok is True
    assert (result.latitude, result.longitude) == (19.076, 72.878)
    assert result.display == "Springfield, Maharashtra, India"
    assert_geocode_call(get, "Springfield")


def test_geocode_skips_indian_result_with_missing_latitude(monkeypatch):
    get = patch_get(
        monkeypatch,
        FakeResponse(
            body={
                "results": [
                    {
                        "name": "Sample",
                        "country_code": "IN",
                        "latitude": None,
                        "longitude": 12.0,
                    },
                    {
                        "name": "Sample",
                        "country_code": "IN",
                        "latitude": 13.0,
                        "longitude": 14.0,
                    },
                ]
            }
        ),
    )
    result = weather.geocode("Sample")
    assert result.ok is True
    assert (result.latitude, result.longitude) == (13.0, 14.0)
    assert_geocode_call(get, "Sample")


def test_geocode_skips_indian_result_with_missing_name(monkeypatch):
    get = patch_get(
        monkeypatch,
        FakeResponse(
            body={
                "results": [
                    {"country_code": "IN", "latitude": 1.0, "longitude": 2.0},
                    {"name": "Valid", "country_code": "IN", "latitude": 3.0, "longitude": 4.0},
                ]
            }
        ),
    )
    result = weather.geocode("Valid")
    assert result.ok is True
    assert result.name == "Valid"
    assert (result.latitude, result.longitude) == (3.0, 4.0)
    assert_geocode_call(get, "Valid")


def test_geocode_results_string_is_unavailable(monkeypatch):
    get = patch_get(monkeypatch, FakeResponse(body={"results": "not a list"}))
    result = weather.geocode("Example")
    assert result.ok is False
    assert result.reason == "geocoding_unavailable"
    assert_geocode_call(get, "Example")


def test_geocode_missing_admin1_display(monkeypatch):
    get = patch_get(
        monkeypatch,
        FakeResponse(
            body={
                "results": [
                    {
                        "name": "Mumbai",
                        "country": "India",
                        "country_code": "IN",
                        "latitude": 19.076,
                        "longitude": 72.878,
                        "timezone": "Asia/Kolkata",
                    }
                ]
            }
        ),
    )
    result = weather.geocode("Mumbai")
    assert result.ok is True
    assert result.admin1 is None
    assert result.display == "Mumbai, India"
    assert_geocode_call(get, "Mumbai")


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("timeout", "geocoding_unavailable"),
        ("connection", "geocoding_unavailable"),
        ("http_500", "geocoding_unavailable"),
        ("invalid_json", "geocoding_unavailable"),
        ("json_list", "geocoding_unavailable"),
    ],
)
def test_geocode_failures(monkeypatch, case, expected_reason):
    if case == "timeout":
        get = patch_get(monkeypatch, side_effect=requests.Timeout("timeout"))
    elif case == "connection":
        get = patch_get(monkeypatch, side_effect=requests.ConnectionError("connection"))
    elif case == "http_500":
        get = patch_get(monkeypatch, FakeResponse(status_code=500, body={}))
    elif case == "invalid_json":
        get = patch_get(monkeypatch, FakeResponse(json_error=ValueError("invalid JSON")))
    else:
        get = patch_get(monkeypatch, FakeResponse(body=[{"country_code": "IN"}]))
    result = weather.geocode("Example")
    assert result.ok is False
    assert result.reason == expected_reason
    get.assert_called_once()
    assert_geocode_call(get, "Example")


BASE_FIELDS = {"current": [], "hourly": ["uv_index"], "daily": []}


def forecast_body():
    return {
        "latitude": 12.3,
        "longitude": 45.6,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "current": {"time": "2026-11-13T12:00", "temperature_2m": 25},
        "current_units": {"temperature_2m": "°C"},
        "hourly": {"time": ["2026-11-13T12:00"], "uv_index": [5]},
        "hourly_units": {"uv_index": "index"},
    }


def assert_weather_call(get, fields=BASE_FIELDS):
    current = list(dict.fromkeys(fields["current"]))
    if weather.NOW_ANCHOR_FIELD not in current:
        current.append(weather.NOW_ANCHOR_FIELD)
    params = {
        "latitude": 12.3,
        "longitude": 45.6,
        "forecast_days": 2,
        "timezone": "auto",
        "current": ",".join(current),
    }
    for group in ("hourly", "daily"):
        if fields[group]:
            params[group] = ",".join(dict.fromkeys(fields[group]))
    get.assert_called_once_with(weather.FORECAST_URL, params=params, timeout=10)


def assert_weather_failure(monkeypatch, response=None, side_effect=None, fields=BASE_FIELDS):
    get = patch_get(monkeypatch, response=response, side_effect=side_effect)
    result = weather.fetch_weather(12.3, 45.6, fields)
    assert result.ok is False
    assert result.reason == "weather_unavailable"
    get.assert_called_once()
    assert_weather_call(get, fields)


def test_forecast_http_400_error_body(monkeypatch):
    assert_weather_failure(monkeypatch, FakeResponse(status_code=400, body={"error": True, "reason": "bad"}))


def test_forecast_http_200_error_body(monkeypatch):
    assert_weather_failure(monkeypatch, FakeResponse(body={"error": True, "reason": "bad"}))


def test_forecast_http_429(monkeypatch):
    assert_weather_failure(monkeypatch, FakeResponse(status_code=429, body={}))


def test_forecast_timeout(monkeypatch):
    assert_weather_failure(monkeypatch, side_effect=requests.Timeout("timeout"))


def test_forecast_connection_error(monkeypatch):
    assert_weather_failure(monkeypatch, side_effect=requests.ConnectionError("connection"))


def test_forecast_invalid_json(monkeypatch):
    assert_weather_failure(monkeypatch, FakeResponse(json_error=ValueError("invalid JSON")))


def test_forecast_json_list(monkeypatch):
    assert_weather_failure(monkeypatch, FakeResponse(body=["not", "an", "object"]))


def test_forecast_missing_current_time(monkeypatch):
    body = forecast_body()
    body["current"].pop("time")
    assert_weather_failure(monkeypatch, FakeResponse(body=body))


def test_forecast_missing_current_group(monkeypatch):
    body = forecast_body()
    body.pop("current")
    assert_weather_failure(monkeypatch, FakeResponse(body=body))


def test_forecast_missing_hourly_group(monkeypatch):
    body = forecast_body()
    body.pop("hourly")
    assert_weather_failure(monkeypatch, FakeResponse(body=body))


def test_forecast_missing_daily_group(monkeypatch):
    fields = {"current": [], "hourly": [], "daily": ["precipitation_sum"]}
    body = forecast_body()
    body.pop("daily", None)
    assert_weather_failure(monkeypatch, FakeResponse(body=body), fields=fields)


def test_forecast_requested_variable_missing(monkeypatch):
    body = forecast_body()
    body["hourly"].pop("uv_index")
    assert_weather_failure(monkeypatch, FakeResponse(body=body))


def test_forecast_mismatched_array_lengths(monkeypatch):
    body = forecast_body()
    body["hourly"]["time"].append("2026-11-13T13:00")
    assert_weather_failure(monkeypatch, FakeResponse(body=body))


def test_forecast_success_params_and_facts(monkeypatch):
    fields = {
        "current": ["apparent_temperature"],
        "hourly": ["uv_index", "temperature_2m"],
        "daily": ["precipitation_sum"],
    }
    body = forecast_body()
    body["current"].update({"temperature_2m": None, "apparent_temperature": 22})
    body["current_units"]["apparent_temperature"] = "°C"
    body["hourly"].update({"uv_index": [5, 6], "temperature_2m": [20, 21], "time": ["t1", "t2"]})
    body["hourly_units"]["temperature_2m"] = "°C"
    body["daily"] = {"time": ["d1"], "precipitation_sum": [0]}
    body["daily_units"] = {"precipitation_sum": "mm"}
    get = patch_get(monkeypatch, FakeResponse(body=body))

    result = weather.fetch_weather(12.3, 45.6, fields)

    assert result.ok is True
    assert result.reason is None
    assert result.facts["now"] == body["current"]["time"]
    assert result.facts["current"]["temperature_2m"] is None
    assert result.facts["units"] == {
        "current": body["current_units"],
        "hourly": body["hourly_units"],
        "daily": body["daily_units"],
    }
    assert result.facts["hourly"]["uv_index"] == [5, 6]
    assert result.facts["hourly"]["time"] == body["hourly"]["time"]
    assert result.facts["daily"]["time"] == body["daily"]["time"]
    assert result.facts["daily"]["precipitation_sum"] == [0]
    assert_weather_call(get, fields)
    current_param = get.call_args.kwargs["params"]["current"]
    assert current_param.split(",").count(weather.NOW_ANCHOR_FIELD) == 1
