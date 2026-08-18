from __future__ import annotations

import os
from typing import Any

import requests


NWS_BASE = "https://api.weather.gov"


def _headers() -> dict[str, str]:
    contact = (os.getenv("SYNC_WEATHER_CONTACT") or "https://syncworksapp.com").strip()
    return {
        "User-Agent": f"SyncWorks-SYNC-Assistant/1.0 ({contact})",
        "Accept": "application/geo+json, application/json",
    }


def _coords(location: dict[str, Any] | None):
    location = location or {}
    try:
        lat = float(location.get("latitude"))
        lon = float(location.get("longitude"))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError):
        pass
    return None


def weather_for_location(location: dict[str, Any] | None) -> dict[str, Any]:
    coords = _coords(location)
    if not coords:
        return {"available": False, "reason": "LOCATION_REQUIRED"}
    lat, lon = coords
    try:
        point = requests.get(f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}", headers=_headers(), timeout=12)
        point.raise_for_status()
        point_data = point.json().get("properties") or {}
        forecast_url = point_data.get("forecast")
        if not forecast_url:
            return {"available": False, "reason": "FORECAST_UNAVAILABLE"}
        forecast = requests.get(forecast_url, headers=_headers(), timeout=12)
        forecast.raise_for_status()
        periods = (forecast.json().get("properties") or {}).get("periods") or []
        current = periods[0] if periods else {}
        next_period = periods[1] if len(periods) > 1 else {}
        alerts = requests.get(
            f"{NWS_BASE}/alerts/active",
            headers=_headers(),
            params={"point": f"{lat:.4f},{lon:.4f}"},
            timeout=12,
        )
        alert_rows = []
        if alerts.ok:
            for feature in (alerts.json().get("features") or [])[:5]:
                props = feature.get("properties") or {}
                alert_rows.append({
                    "event": props.get("event") or "Weather alert",
                    "severity": props.get("severity") or "Unknown",
                    "headline": props.get("headline") or "",
                    "expires": props.get("expires"),
                })
        return {
            "available": True,
            "provider": "NWS",
            "location": {
                "label": (location or {}).get("label") or point_data.get("relativeLocation", {}).get("properties", {}).get("city") or "Current location",
                "latitude": lat,
                "longitude": lon,
            },
            "current_period": {
                "name": current.get("name") or "Today",
                "temperature": current.get("temperature"),
                "temperature_unit": current.get("temperatureUnit") or "F",
                "short_forecast": current.get("shortForecast") or "",
                "detail": current.get("detailedForecast") or "",
                "precipitation_probability": (current.get("probabilityOfPrecipitation") or {}).get("value"),
                "wind_speed": current.get("windSpeed") or "",
                "wind_direction": current.get("windDirection") or "",
            },
            "next_period": {
                "name": next_period.get("name") or "",
                "temperature": next_period.get("temperature"),
                "temperature_unit": next_period.get("temperatureUnit") or "F",
                "short_forecast": next_period.get("shortForecast") or "",
                "precipitation_probability": (next_period.get("probabilityOfPrecipitation") or {}).get("value"),
            },
            "alerts": alert_rows,
        }
    except requests.RequestException as exc:
        return {"available": False, "reason": "PROVIDER_ERROR", "detail": str(exc)[:180]}
