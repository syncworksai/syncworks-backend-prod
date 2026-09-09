from __future__ import annotations

import logging
from typing import Any

import requests
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def _safe_float(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_city(address: dict[str, Any]) -> str:
    for key in ("city", "town", "village", "municipality", "hamlet", "county"):
        value = str(address.get(key) or "").strip()
        if value:
            return value
    return ""


def _street_line(address: dict[str, Any], fallback: str = "") -> str:
    house_number = str(address.get("house_number") or "").strip()
    road = str(
        address.get("road")
        or address.get("pedestrian")
        or address.get("footway")
        or address.get("residential")
        or ""
    ).strip()
    value = " ".join(part for part in (house_number, road) if part).strip()
    return value or str(fallback or "").split(",", 1)[0].strip()


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    display_name = str(item.get("display_name") or "").strip()
    return {
        "id": str(item.get("place_id") or item.get("osm_id") or display_name),
        "name": str(item.get("name") or address.get("amenity") or address.get("building") or "").strip(),
        "label": display_name,
        "address_line1": _street_line(address, display_name),
        "city": _best_city(address),
        "state": str(address.get("state") or address.get("region") or "").strip(),
        "postal_code": str(address.get("postcode") or "").strip(),
        "country": str(address.get("country") or "").strip(),
        "latitude": _safe_float(item.get("lat")),
        "longitude": _safe_float(item.get("lon")),
        "provider": "OPENSTREETMAP",
    }


class CalendarPlaceSearchView(APIView):
    """Explicit address lookup for the Personal Calendar composer.

    Search is intentionally request-driven instead of autocomplete-spamming the
    upstream geocoder. Results are normalized so the frontend can populate the
    same event location fields used by Maps, routing and travel assist.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = str(request.query_params.get("q") or "").strip()
        if len(query) < 3:
            return Response(
                {"detail": "Enter at least 3 characters to search an address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(query) > 180:
            return Response(
                {"detail": "Address searches must be 180 characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"calendar-place-search:v1:{query.casefold()}"
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return Response({"results": cached, "provider": "OPENSTREETMAP", "cached": True})

        try:
            upstream = requests.get(
                NOMINATIM_SEARCH_URL,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": 8,
                    "countrycodes": "us",
                },
                headers={
                    "User-Agent": "SyncWorks-Calendar/1.0 (https://syncworksapp.com)",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=10,
            )
            upstream.raise_for_status()
            payload = upstream.json()
        except (requests.RequestException, ValueError):
            logger.exception("Calendar place search provider failed")
            return Response(
                {
                    "detail": "Address search is temporarily unavailable. You can still enter the address manually.",
                    "results": [],
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        results = [
            _normalize_result(item)
            for item in payload
            if isinstance(item, dict)
        ]
        results = [item for item in results if item.get("label")][:8]
        cache.set(cache_key, results, 60 * 60)
        return Response({"results": results, "provider": "OPENSTREETMAP", "cached": False})
