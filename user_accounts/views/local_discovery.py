from __future__ import annotations

import math
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
    return {
        **location,
        "latitude": resolved.get("latitude"),
        "longitude": resolved.get("longitude"),
        "label": resolved.get("label") or location.get("label"),
    }


def _distance_miles(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    try:
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlambda = math.radians(float(lng2) - float(lng1))
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        miles = 3958.7613 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(miles, 1)
    except (TypeError, ValueError):
        return None


def _place_row(item: dict, origin: dict | None = None) -> dict:
    geometry = ((item.get("geometry") or {}).get("location") or {})
    rating = item.get("rating")
    reviews = item.get("user_ratings_total") or 0
    open_now = ((item.get("opening_hours") or {}).get("open_now"))
    distance = _distance_miles(
        (origin or {}).get("latitude"),
        (origin or {}).get("longitude"),
        geometry.get("lat"),
        geometry.get("lng"),
    )

    score = 0.0
    if rating is not None:
        score += max(0.0, min(float(rating), 5.0)) * 14
    score += min(math.log10(max(int(reviews), 1)) * 8, 28)
    if open_now is True:
        score += 12
    elif open_now is False:
        score -= 8
    if distance is not None:
        score += max(0, 18 - min(distance, 18))
    score = round(max(0, min(score, 100)), 1)

    reasons = []
    if open_now is True:
        reasons.append("Open now")
    if rating is not None and float(rating) >= 4.5:
        reasons.append("Highly rated")
    elif rating is not None and float(rating) >= 4.0:
        reasons.append("Well rated")
    if reviews >= 250:
        reasons.append("Popular")
    if distance is not None:
        if distance <= 2:
            reasons.append("Very close")
        elif distance <= 5:
            reasons.append("Nearby")

    return {
        "place_id": item.get("place_id") or "",
        "name": item.get("name") or "",
        "address": item.get("formatted_address") or item.get("vicinity") or "",
        "rating": rating,
        "user_ratings_total": reviews,
        "price_level": item.get("price_level"),
        "open_now": open_now,
        "types": item.get("types") or [],
        "latitude": geometry.get("lat"),
        "longitude": geometry.get("lng"),
        "business_status": item.get("business_status") or "",
        "distance_miles": distance,
        "sync_score": score,
        "why": reasons[:3],
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

        rows = [_place_row(item, location) for item in (payload.get("results") or [])[:20]]
        rows.sort(key=lambda item: (item.get("sync_score") or 0, item.get("user_ratings_total") or 0), reverse=True)
        for index, row in enumerate(rows):
            row["rank"] = index + 1
            row["recommended"] = index == 0 and bool(rows)

        return {
            "available": True,
            "provider": "GOOGLE_PLACES",
            "results": rows,
            "decision": {
                "recommended_place_id": rows[0].get("place_id") if rows else "",
                "recommended_name": rows[0].get("name") if rows else "",
                "reason": "SYNC ranks nearby results using distance, rating, popularity, and whether the place is open now.",
            },
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        return {
            "available": False,
            "reason": "PLACES_PROVIDER_ERROR",
            "detail": str(exc)[:180],
            "results": [],
        }


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
