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


def reverse_geocode(latitude: float, longitude: float) -> dict[str, Any]:
    """Resolve device coordinates to a service-ready address without storing them."""
    api_key = _maps_key()
    if not api_key:
        return {
            "available": False,
            "reason": "GEOCODING_NOT_CONFIGURED",
            "latitude": float(latitude),
            "longitude": float(longitude),
        }

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{float(latitude)},{float(longitude)}", "key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        provider_status = str(payload.get("status") or "")
        if provider_status != "OK":
            return {
                "available": False,
                "reason": provider_status or "REVERSE_GEOCODING_FAILED",
                "detail": str(payload.get("error_message") or "")[:180],
                "latitude": float(latitude),
                "longitude": float(longitude),
            }

        result = (payload.get("results") or [{}])[0]
        components = result.get("address_components") or []

        def component(*types: str) -> str:
            wanted = set(types)
            for item in components:
                if wanted.intersection(item.get("types") or []):
                    return str(item.get("short_name") or item.get("long_name") or "")
            return ""

        street_number = component("street_number")
        route = component("route")
        street = " ".join(part for part in [street_number, route] if part).strip()
        city = component("locality", "postal_town") or component("administrative_area_level_2")
        state = component("administrative_area_level_1")
        postal_code = component("postal_code")
        country = component("country") or "US"

        return {
            "available": True,
            "provider": "GOOGLE_GEOCODING",
            "label": result.get("formatted_address") or "",
            "address_line1": street or result.get("formatted_address") or "",
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": country,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "place_id": result.get("place_id") or "",
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        return {
            "available": False,
            "reason": "GEOCODING_PROVIDER_ERROR",
            "detail": str(exc)[:180],
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
