from __future__ import annotations

from datetime import timedelta

import requests
from django.utils import timezone

from personal_calendar.travel_assist import (
    NWS_POINTS_URL,
    NWS_USER_AGENT,
    TravelAssistError,
    _geocode_destination,
    _google_key,
    _weather_risk,
)


def _period_weather(period):
    precip = (period.get("probabilityOfPrecipitation") or {}).get("value")
    precip = int(round(float(precip or 0)))
    wind_text = str(period.get("windSpeed") or "0 mph").split(" ")[0].split("-")[0]
    try:
        wind_mph = int(round(float(wind_text)))
    except ValueError:
        wind_mph = 0
    short_forecast = period.get("shortForecast") or ""
    return {
        "start_at": period.get("startTime"),
        "temperature": period.get("temperature"),
        "temperature_unit": period.get("temperatureUnit") or "F",
        "precipitation_probability": precip,
        "wind_speed": period.get("windSpeed") or "",
        "wind_direction": period.get("windDirection") or "",
        "short_forecast": short_forecast,
        "risk": _weather_risk(short_forecast, precip, wind_mph),
    }


def _hourly_periods(event):
    destination = _geocode_destination(event, _google_key())
    if not destination:
        raise TravelAssistError("Household coordinates are required for weather planning. Add a valid Household address and configure geocoding.")
    if str(event.country or "US").upper() != "US":
        raise TravelAssistError("Household weather planning currently supports U.S. addresses.")

    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    point_url = NWS_POINTS_URL.format(
        lat=round(float(destination["latitude"]), 4),
        lng=round(float(destination["longitude"]), 4),
    )
    try:
        point_response = requests.get(point_url, headers=headers, timeout=8)
        point_response.raise_for_status()
        hourly_url = point_response.json().get("properties", {}).get("forecastHourly")
        if not hourly_url:
            raise TravelAssistError("NWS hourly weather is unavailable for this Household address.")
        hourly_response = requests.get(hourly_url, headers=headers, timeout=8)
        hourly_response.raise_for_status()
    except requests.RequestException as exc:
        raise TravelAssistError("Weather provider is temporarily unavailable.") from exc

    periods = hourly_response.json().get("properties", {}).get("periods") or []
    if not periods:
        raise TravelAssistError("No hourly weather periods were returned for this Household address.")
    return periods


def _parse_period_start(period):
    value = period.get("startTime")
    if not value:
        return None
    try:
        return timezone.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_household_weather_plan(event, *, search_hours=72):
    if not event.start_at:
        raise TravelAssistError("Schedule this task before checking weather windows.")

    now = timezone.now()
    if event.start_at < now - timedelta(hours=1) or event.start_at > now + timedelta(days=7):
        raise TravelAssistError("Hourly weather planning is available when the task is within the next 7 days.")

    periods = _hourly_periods(event)
    target = event.start_at
    parsed = []
    for period in periods:
        start = _parse_period_start(period)
        if not start:
            continue
        parsed.append((start, _period_weather(period)))
    if not parsed:
        raise TravelAssistError("No usable hourly weather periods were returned.")

    current_start, current = min(parsed, key=lambda row: abs((row[0] - target).total_seconds()))
    current["start_at"] = current_start.isoformat()

    window_start = max(now, target - timedelta(hours=min(search_hours, 24)))
    window_end = min(now + timedelta(days=7), target + timedelta(hours=search_hours))
    alternatives = []
    for start, weather in parsed:
        if start < window_start or start > window_end:
            continue
        local_hour = start.astimezone(target.tzinfo).hour if target.tzinfo else start.hour
        if local_hour < 7 or local_hour > 20:
            continue
        if weather["risk"] != "LOW" or weather["precipitation_probability"] >= 30:
            continue
        candidate = dict(weather)
        candidate["start_at"] = start.isoformat()
        candidate["hours_from_current"] = round((start - target).total_seconds() / 3600, 1)
        alternatives.append((abs((start - target).total_seconds()), start < target, candidate))

    alternatives.sort(key=lambda row: (row[0], row[1]))
    choices = [row[2] for row in alternatives[:3]]

    if current["risk"] == "LOW":
        recommendation = "KEEP"
        message = "Weather currently looks suitable for the scheduled time."
        suggested = current["start_at"]
    elif choices:
        recommendation = "MOVE"
        suggested = choices[0]["start_at"]
        message = "Weather may interfere with the scheduled time. SYNC found a lower-risk nearby window."
    else:
        recommendation = "HOLD"
        suggested = None
        message = "Weather may interfere and no low-risk nearby window is available yet. A weather hold is recommended."

    return {
        "status": "READY",
        "provider": "NWS",
        "task_start_at": target.isoformat(),
        "current": current,
        "recommendation": recommendation,
        "suggested_start_at": suggested,
        "alternatives": choices,
        "message": message,
        "generated_at": timezone.now().isoformat(),
    }
