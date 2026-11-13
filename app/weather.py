from dataclasses import dataclass
from typing import Any

import requests


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NOW_ANCHOR_FIELD = "temperature_2m"


@dataclass(frozen=True)
class GeoResult:
    ok: bool
    reason: str | None = None
    name: str | None = None
    admin1: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    display: str | None = None


@dataclass(frozen=True)
class WeatherResult:
    ok: bool
    reason: str | None = None
    facts: dict[str, Any] | None = None


def geocode(name: str) -> GeoResult:
    params = {"name": name, "count": 10, "countryCode": "IN"}
    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=10)
        if response.status_code != 200:
            return GeoResult(ok=False, reason="geocoding_unavailable")
        body = response.json()
    except (requests.RequestException, ValueError):
        return GeoResult(ok=False, reason="geocoding_unavailable")

    if not isinstance(body, dict):
        return GeoResult(ok=False, reason="geocoding_unavailable")
    if "results" not in body:
        return GeoResult(ok=False, reason="location_not_found")
    results = body["results"]
    if not isinstance(results, list):
        return GeoResult(ok=False, reason="geocoding_unavailable")
    indian_results = [
        result
        for result in results
        if isinstance(result, dict)
        and result.get("country_code") == "IN"
        and isinstance(result.get("name"), str)
        and bool(result["name"].strip())
        and isinstance(result.get("latitude"), (int, float))
        and not isinstance(result.get("latitude"), bool)
        and isinstance(result.get("longitude"), (int, float))
        and not isinstance(result.get("longitude"), bool)
    ]
    if not indian_results:
        return GeoResult(ok=False, reason="location_not_found")

    result = indian_results[0]
    location_name = result.get("name")
    admin1 = result.get("admin1")
    display = f"{location_name}, {admin1}, India" if admin1 else f"{location_name}, India"
    return GeoResult(
        ok=True,
        name=location_name,
        admin1=admin1,
        country=result.get("country"),
        latitude=result.get("latitude"),
        longitude=result.get("longitude"),
        timezone=result.get("timezone"),
        display=display,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def fetch_weather(lat: float, lon: float, fields: dict[str, list[str]]) -> WeatherResult:
    requested = {
        group: _unique(fields[group])
        for group in ("current", "hourly", "daily")
    }
    if NOW_ANCHOR_FIELD not in requested["current"]:
        requested["current"].append(NOW_ANCHOR_FIELD)

    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "forecast_days": 2,
        "timezone": "auto",
    }
    for group, variables in requested.items():
        if variables:
            params[group] = ",".join(variables)

    try:
        response = requests.get(FORECAST_URL, params=params, timeout=10)
        if response.status_code != 200:
            return WeatherResult(ok=False, reason="weather_unavailable")
        body = response.json()
    except (requests.RequestException, ValueError):
        return WeatherResult(ok=False, reason="weather_unavailable")

    if not isinstance(body, dict) or body.get("error") is True:
        return WeatherResult(ok=False, reason="weather_unavailable")

    current = body.get("current")
    if not isinstance(current, dict) or "time" not in current or current["time"] is None:
        return WeatherResult(ok=False, reason="weather_unavailable")
    for variable in requested["current"]:
        if variable not in current:
            return WeatherResult(ok=False, reason="weather_unavailable")

    groups: dict[str, dict[str, Any]] = {"current": current}
    for group in ("hourly", "daily"):
        if not requested[group]:
            continue
        values = body.get(group)
        if not isinstance(values, dict):
            return WeatherResult(ok=False, reason="weather_unavailable")
        times = values.get("time")
        if not isinstance(times, list):
            return WeatherResult(ok=False, reason="weather_unavailable")
        for variable in requested[group]:
            if variable not in values or not isinstance(values[variable], list):
                return WeatherResult(ok=False, reason="weather_unavailable")
            if len(values[variable]) != len(times):
                return WeatherResult(ok=False, reason="weather_unavailable")
        groups[group] = values

    facts = {
        "now": current["time"],
        "timezone": body.get("timezone"),
        "utc_offset_seconds": body.get("utc_offset_seconds"),
        "grid_latitude": body.get("latitude"),
        "grid_longitude": body.get("longitude"),
        "units": {
            "current": body.get("current_units"),
            "hourly": body.get("hourly_units"),
            "daily": body.get("daily_units"),
        },
        "current": {variable: current[variable] for variable in requested["current"]},
        "hourly": {
            "time": groups["hourly"]["time"],
            **{variable: groups["hourly"][variable] for variable in requested["hourly"]},
        },
        "daily": {
            "time": groups["daily"]["time"],
            **{variable: groups["daily"][variable] for variable in requested["daily"]},
        },
    }
    return WeatherResult(ok=True, facts=facts)
