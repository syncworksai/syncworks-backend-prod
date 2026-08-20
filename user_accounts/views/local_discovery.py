from __future__ import annotations

import os

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sync_ai.location_intelligence import geocode_address, reverse_geocode
from user_accounts.views.context_router import resolve_location_context

CATEGORY_QUERIES = {
    "FOOD": "restaurants",
    "RETAIL": "shopping",
    "SERVICES": "local services",
    "EVENTS": "things to do",
    "NEARBY": "places nearby",
}


def _maps_key() -> str:
    return (os.getenv("GOOGLE_MAPS_SERVER_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()


def _ensure_coordinates(location: dict | None) -> dict | None:
    if not location:
        return None
    lat = location.get("latitude")
    lng = location.get("longitude")
    if lat is not None and lng is not None:
        return location
    address = location.get("formatted_address") or location.get("label") or ""
    if not address:
        return location
    resolved = geocode_address(address)
    if not resolved.get("available"):
        return location
    return {**location, "latitude": resolved.get("latitude"), "longitude": resolved.get("longitude"), "label": resolved.get("label") or location.get("label")}


def _place_row(item: dict) -> dict:
    geometry = ((item.get("geometry") or {}).get("location") or {})
    return {
        "place_id": item.get("place_id") or "",
        "name": item.get("name") or "",
        "address": item.get("formatted_address") or item.get("vicinity") or "",
        "rating": item.get("rating"),
        "user_ratings_total": item.get("user_ratings_total") or 0,
        "price_level": item.get("price_level"),
        "open_now": ((item.get("opening_hours") or {}).get("open_now")),
        "types": item.get("types") or [],
        "latitude": geometry.get("lat"),
        "longitude": geometry.get("lng"),
        "business_status": item.get("business_status") or "",
    }


def search_places(query: str, location: dict, radius_meters: int = 12000) -> dict:
    api_key = _maps_key()
    if not api_key:
        return {"available": False, "reason": "PLACES_NOT_CONFIGURED", "results": []}

    location = _ensure_coordinates(location)
    lat = location.get("latitude") if location else None
    lng = location.get("longitude") if location else None
    if lat is None or lng is None:
        return {"available": False, "reason": "LOCATION_COORDINATES_REQUIRED", "results": []}

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={
                "query": query,
                "location": f"{float(lat)},{float(lng)}",
                "radius": max(1000, min(int(radius_meters), 50000)),
                "key": api_key,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        provider_status = str(payload.get("status") or "")
        if provider_status not in {"OK", "ZERO_RESULTS"}:
            return {
                "available": False,
                "reason": provider_status or "PLACES_SEARCH_FAILED",
                "detail": str(payload.get("error_message") or "")[:180],
                "results": [],
            }
        return {
            "available": True,
            "provider": "GOOGLE_PLACES",
            "results": [_place_row(item) for item in (payload.get("results") or [])[:20]],
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        return {"available": False, "reason": "PLACES_PROVIDER_ERROR", "detail": str(exc)[:180], "results": []}


class LocalDiscoveryAPIView(APIView):
    """Context-aware discovery for food, retail, services, events and nearby places."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        category = str(request.data.get("category") or "NEARBY").strip().upper()
        if category not in CATEGORY_QUERIES:
            category = "NEARBY"

        context = resolve_location_context(request.user, category, request.data)
        location = context.get("location")
        if not location:
            return Response(
                {
                    "available": False,
                    "reason": "LOCATION_REQUIRED",
                    "context": context,
                    "results": [],
                    "detail": "Add a Home address or allow current location to discover nearby places.",
                },
                status=status.HTTP_200_OK,
            )

        if context.get("source") == "CURRENT" and location.get("latitude") is not None and location.get("longitude") is not None:
            resolved = reverse_geocode(location["latitude"], location["longitude"])
            if resolved.get("available"):
                location = {**location, **resolved}
                context["location"] = location

        user_query = str(request.data.get("query") or "").strip()
        base_query = CATEGORY_QUERIES[category]
        query = f"{user_query} {base_query}".strip() if user_query else base_query
        radius = request.data.get("radius_meters") or 12000
        result = search_places(query, location, radius)

        return Response(
            {
                **result,
                "category": category,
                "query": query,
                "context": context,
                "location": location,
                "privacy": {
                    "current_location_persisted": False,
                    "home_overwritten": False,
                },
            }
        )
