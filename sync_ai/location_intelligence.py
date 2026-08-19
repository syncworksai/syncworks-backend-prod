from __future__ import annotations

import os
from typing import Any

import requests


def _maps_key() -> str:
    return (
        os.getenv("GOOGLE_MAPS_SERVER_API_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or ""
    ).strip()


def geocode_address(address: str) -> dict[str, Any]:
    query = str(address or "").strip()
    if not query:
        return {"available": False, "reason": "ADDRESS_REQUIRED"}

    api_key = _maps_key()
    if not api_key:
        return {"available": False, "reason": "GEOCODING_NOT_CONFIGURED"}

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status") or "")
        if status != "OK":
            return {
                "available": False,
                "reason": status or "GEOCODING_FAILED",
                "detail": str(payload.get("error_message") or "")[:180],
            }
        result = (payload.get("results") or [{}])[0]
        location = ((result.get("geometry") or {}).get("location") or {})
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is None or lng is None:
            return {"available": False, "reason": "COORDINATES_UNAVAILABLE"}
        return {
            "available": True,
            "provider": "GOOGLE_GEOCODING",
            "label": result.get("formatted_address") or query,
            "latitude": float(lat),
            "longitude": float(lng),
            "place_id": result.get("place_id") or "",
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        return {
            "available": False,
            "reason": "GEOCODING_PROVIDER_ERROR",
            "detail": str(exc)[:180],
        }
