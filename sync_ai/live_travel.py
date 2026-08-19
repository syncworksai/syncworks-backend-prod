from __future__ import annotations

import math
import os
from datetime import timedelta
from typing import Any

import requests


def _coords(value: dict[str, Any] | None):
    value = value or {}
    try:
        lat = float(value.get("latitude"))
        lon = float(value.get("longitude"))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError):
        pass
    return None


def _seconds(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text.endswith("s"):
        return None
    try:
        return max(0, math.ceil(float(text[:-1])))
    except ValueError:
        return None


def route_minutes(origin: dict[str, Any] | None, destination: dict[str, Any] | None) -> dict[str, Any]:
    start = _coords(origin)
    end = _coords(destination)
    if not start or not end:
        return {"available": False, "reason": "COORDINATES_REQUIRED"}
    # GOOGLE_MAPS_SERVER_API_KEY is the production server-only key used by the
    # Personal Calendar travel engine. Keep the older name as a compatibility
    # fallback so existing Render environments continue to work.
    api_key = (os.getenv("GOOGLE_MAPS_SERVER_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    if not api_key:
        return {"available": False, "reason": "ROUTES_NOT_CONFIGURED"}
    payload = {
        "origin": {"location": {"latLng": {"latitude": start[0], "longitude": start[1]}}},
        "destination": {"location": {"latLng": {"latitude": end[0], "longitude": end[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": False,
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }
    try:
        response = requests.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters",
            },
            timeout=12,
        )
        response.raise_for_status()
        route = (response.json().get("routes") or [{}])[0]
        seconds = _seconds(route.get("duration"))
        if seconds is None:
            return {"available": False, "reason": "ROUTE_UNAVAILABLE"}
        return {
            "available": True,
            "provider": "GOOGLE_ROUTES",
            "minutes": max(1, math.ceil(seconds / 60)),
            "static_minutes": max(1, math.ceil((_seconds(route.get("staticDuration")) or seconds) / 60)),
            "distance_meters": route.get("distanceMeters"),
            "traffic_aware": True,
        }
    except requests.RequestException as exc:
        return {"available": False, "reason": "ROUTE_PROVIDER_ERROR", "detail": str(exc)[:180]}


def leave_plan(*, event_start, arrival_buffer_minutes: int, reminder_minutes: int, travel: dict[str, Any]) -> dict[str, Any]:
    if not event_start:
        return {"available": False}
    travel_minutes = travel.get("minutes") if travel.get("available") else None
    if travel_minutes is None:
        return {
            "available": False,
            "reason": travel.get("reason") or "TRAVEL_TIME_REQUIRED",
            "arrival_buffer_minutes": arrival_buffer_minutes,
            "reminder_minutes": reminder_minutes,
        }
    leave_by = event_start - timedelta(minutes=int(arrival_buffer_minutes or 0) + int(travel_minutes))
    remind_at = leave_by - timedelta(minutes=int(reminder_minutes or 0))
    return {
        "available": True,
        "travel_minutes": int(travel_minutes),
        "arrival_buffer_minutes": int(arrival_buffer_minutes or 0),
        "leave_by": leave_by.isoformat(),
        "remind_at": remind_at.isoformat(),
        "traffic_aware": bool(travel.get("traffic_aware")),
        "distance_meters": travel.get("distance_meters"),
    }
