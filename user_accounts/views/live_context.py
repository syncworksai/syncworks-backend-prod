from __future__ import annotations

import os
from typing import Any

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

OPENWEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall"
MAPBOX_GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coordinates}"


def _openweather_key() -> str:
    return (os.getenv("OPENWEATHER_API_KEY") or "").strip()


def _mapbox_token() -> str:
    return (os.getenv("MAPBOX_ACCESS_TOKEN") or "").strip()


def _number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def _fahrenheit(value: Any) -> float | None:
    number = _number(value)
    return round(number, 1) if number is not None else None


def _mph_from_mps(value: Any) -> float | None:
    number = _number(value)
    return round(number * 2.236936, 1) if number is not None else None


def _miles_from_meters(value: Any) -> float | None:
    number = _number(value)
    return round(number / 1609.344, 1) if number is not None else None


def _minutes(value: Any) -> int | None:
    number = _number(value)
    return max(0, round(number / 60)) if number is not None else None


def _weather_description(row: dict) -> tuple[str, str, str]:
    weather = row.get("weather") or []
    first = weather[0] if weather else {}
    return (
        str(first.get("main") or ""),
        str(first.get("description") or ""),
        str(first.get("icon") or ""),
    )


def _normalize_weather(payload: dict, latitude: float, longitude: float) -> dict:
    current = payload.get("current") or {}
    main, description, icon = _weather_description(current)

    minutely = []
    for item in (payload.get("minutely") or [])[:61]:
        minutely.append(
            {
                "timestamp": item.get("dt"),
                "precipitation_mm": round(float(item.get("precipitation") or 0), 2),
            }
        )

    hourly = []
    for item in (payload.get("hourly") or [])[:12]:
        hourly_main, hourly_description, hourly_icon = _weather_description(item)
        hourly.append(
            {
                "timestamp": item.get("dt"),
                "temp_f": _fahrenheit(item.get("temp")),
                "feels_like_f": _fahrenheit(item.get("feels_like")),
                "precip_probability": round(float(item.get("pop") or 0) * 100),
                "condition": hourly_main,
                "description": hourly_description,
                "icon": hourly_icon,
                "wind_mph": _mph_from_mps(item.get("wind_speed")),
            }
        )

    alerts = []
    for item in (payload.get("alerts") or [])[:8]:
        alerts.append(
            {
                "sender": item.get("sender_name") or "",
                "event": item.get("event") or "Weather alert",
                "start": item.get("start"),
                "end": item.get("end"),
                "description": str(item.get("description") or "")[:1200],
                "tags": item.get("tags") or [],
            }
        )

    next_precip = next((item for item in minutely if (item.get("precipitation_mm") or 0) > 0), None)
    max_precip = max((item.get("precipitation_mm") or 0 for item in minutely), default=0)

    return {
        "available": True,
        "provider": "OPENWEATHER_ONE_CALL_3",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": payload.get("timezone") or "",
            "timezone_offset": payload.get("timezone_offset"),
        },
        "current": {
            "timestamp": current.get("dt"),
            "temp_f": _fahrenheit(current.get("temp")),
            "feels_like_f": _fahrenheit(current.get("feels_like")),
            "condition": main,
            "description": description,
            "icon": icon,
            "humidity": current.get("humidity"),
            "wind_mph": _mph_from_mps(current.get("wind_speed")),
            "wind_degrees": current.get("wind_deg"),
            "uvi": current.get("uvi"),
            "clouds": current.get("clouds"),
            "visibility_miles": _miles_from_meters(current.get("visibility")),
        },
        "minute_forecast": {
            "available": bool(minutely),
            "points": minutely,
            "next_precipitation": next_precip,
            "max_precipitation_mm": round(max_precip, 2),
        },
        "hourly": hourly,
        "alerts": alerts,
    }


def _geocode_destination(query: str, token: str) -> dict:
    response = requests.get(
        MAPBOX_GEOCODE_URL,
        params={
            "q": query,
            "access_token": token,
            "limit": 1,
            "autocomplete": "false",
        },
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        return {"available": False, "reason": "DESTINATION_NOT_FOUND"}
    feature = features[0]
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        return {"available": False, "reason": "DESTINATION_NOT_FOUND"}
    properties = feature.get("properties") or {}
    return {
        "available": True,
        "longitude": coordinates[0],
        "latitude": coordinates[1],
        "label": properties.get("full_address") or properties.get("name") or feature.get("place_name") or query,
    }


def _normalize_route(route: dict, index: int) -> dict:
    duration_seconds = _number(route.get("duration")) or 0
    typical_seconds = _number(route.get("duration_typical"))
    delay_seconds = max(0, duration_seconds - typical_seconds) if typical_seconds is not None else None
    legs = route.get("legs") or []
    incidents = []
    for leg in legs:
        for incident in (leg.get("incidents") or []):
            incidents.append(
                {
                    "type": incident.get("type") or "incident",
                    "description": incident.get("description") or incident.get("long_description") or "",
                    "impact": incident.get("impact") or "",
                    "start_time": incident.get("creation_time") or incident.get("start_time"),
                    "end_time": incident.get("end_time"),
                }
            )

    return {
        "rank": index + 1,
        "duration_seconds": round(duration_seconds),
        "duration_minutes": _minutes(duration_seconds),
        "typical_duration_seconds": round(typical_seconds) if typical_seconds is not None else None,
        "typical_duration_minutes": _minutes(typical_seconds),
        "delay_seconds": round(delay_seconds) if delay_seconds is not None else None,
        "delay_minutes": _minutes(delay_seconds),
        "distance_miles": _miles_from_meters(route.get("distance")),
        "weight": route.get("weight"),
        "incidents": incidents[:10],
    }


class LiveWeatherAPIView(APIView):
    """Return normalized live/minute weather without exposing provider credentials."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        latitude = _number(request.data.get("latitude"), minimum=-90, maximum=90)
        longitude = _number(request.data.get("longitude"), minimum=-180, maximum=180)
        if latitude is None or longitude is None:
            return Response(
                {"available": False, "reason": "VALID_LOCATION_REQUIRED", "detail": "Allow current location and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        key = _openweather_key()
        if not key:
            return Response(
                {"available": False, "reason": "WEATHER_NOT_CONFIGURED", "detail": "Live weather is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            response = requests.get(
                OPENWEATHER_URL,
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "appid": key,
                    "units": "imperial",
                    "exclude": "daily",
                },
                timeout=15,
            )
            response.raise_for_status()
            return Response(_normalize_weather(response.json(), latitude, longitude))
        except requests.HTTPError as exc:
            provider_status = getattr(exc.response, "status_code", None)
            return Response(
                {
                    "available": False,
                    "reason": "WEATHER_PROVIDER_ERROR",
                    "provider_status": provider_status,
                    "detail": "OpenWeather could not return live weather. Verify One Call access if this persists.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (requests.RequestException, TypeError, ValueError):
            return Response(
                {"available": False, "reason": "WEATHER_PROVIDER_UNAVAILABLE", "detail": "Live weather is temporarily unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class LiveTrafficAPIView(APIView):
    """Return Mapbox driving-traffic ETA, typical ETA, delay and alternatives."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        origin_latitude = _number(request.data.get("latitude"), minimum=-90, maximum=90)
        origin_longitude = _number(request.data.get("longitude"), minimum=-180, maximum=180)
        if origin_latitude is None or origin_longitude is None:
            return Response(
                {"available": False, "reason": "VALID_ORIGIN_REQUIRED", "detail": "Allow current location and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = _mapbox_token()
        if not token:
            return Response(
                {"available": False, "reason": "TRAFFIC_NOT_CONFIGURED", "detail": "Live traffic is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        destination_latitude = _number(request.data.get("destination_latitude"), minimum=-90, maximum=90)
        destination_longitude = _number(request.data.get("destination_longitude"), minimum=-180, maximum=180)
        destination_label = str(request.data.get("destination_label") or request.data.get("destination") or "").strip()

        try:
            if destination_latitude is None or destination_longitude is None:
                if not destination_label:
                    return Response(
                        {"available": False, "reason": "DESTINATION_REQUIRED", "detail": "Enter a destination to check live traffic."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                destination = _geocode_destination(destination_label, token)
                if not destination.get("available"):
                    return Response(
                        {"available": False, "reason": "DESTINATION_NOT_FOUND", "detail": "SYNC could not find that destination."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                destination_latitude = float(destination["latitude"])
                destination_longitude = float(destination["longitude"])
                destination_label = str(destination.get("label") or destination_label)

            coordinates = f"{origin_longitude},{origin_latitude};{destination_longitude},{destination_latitude}"
            response = requests.get(
                MAPBOX_DIRECTIONS_URL.format(coordinates=coordinates),
                params={
                    "access_token": token,
                    "alternatives": "true",
                    "overview": "false",
                    "steps": "false",
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            routes = [_normalize_route(route, index) for index, route in enumerate((payload.get("routes") or [])[:3])]
            if not routes:
                return Response(
                    {"available": False, "reason": "ROUTE_NOT_FOUND", "detail": "No drivable route was found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "available": True,
                    "provider": "MAPBOX_DRIVING_TRAFFIC",
                    "origin": {"latitude": origin_latitude, "longitude": origin_longitude},
                    "destination": {
                        "label": destination_label,
                        "latitude": destination_latitude,
                        "longitude": destination_longitude,
                    },
                    "best": routes[0],
                    "routes": routes,
                }
            )
        except requests.HTTPError as exc:
            provider_status = getattr(exc.response, "status_code", None)
            return Response(
                {
                    "available": False,
                    "reason": "TRAFFIC_PROVIDER_ERROR",
                    "provider_status": provider_status,
                    "detail": "Mapbox could not return live traffic. Verify the access token if this persists.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (requests.RequestException, TypeError, ValueError):
            return Response(
                {"available": False, "reason": "TRAFFIC_PROVIDER_UNAVAILABLE", "detail": "Live traffic is temporarily unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
