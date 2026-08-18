from __future__ import annotations

import os
from datetime import timedelta

import requests
from django.utils import timezone

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lng}"
NWS_USER_AGENT = os.environ.get("NWS_USER_AGENT", "SyncWorks/1.0 (syncworks.ai@gmail.com)")


class TravelAssistError(RuntimeError):
    pass


def _seconds(value):
    text = str(value or "0s").strip().lower()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return max(0, int(round(float(text))))
    except (TypeError, ValueError):
        return 0


def _event_address(event):
    parts = [
        event.address_line1,
        event.address_line2,
        event.city,
        event.state,
        event.postal_code,
        event.country,
    ]
    address = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    return address or str(event.location_name or "").strip()


def _google_key():
    return str(
        os.environ.get("GOOGLE_MAPS_SERVER_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or ""
    ).strip()


def _geocode_destination(event, api_key):
    if event.latitude is not None and event.longitude is not None:
        return {
            "latitude": float(event.latitude),
            "longitude": float(event.longitude),
            "source": "EVENT",
        }
    address = _event_address(event)
    if not address or not api_key:
        return None
    response = requests.get(
        GOOGLE_GEOCODE_URL,
        params={"address": address, "key": api_key},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "OK" or not payload.get("results"):
        return None
    location = payload["results"][0].get("geometry", {}).get("location", {})
    if location.get("lat") is None or location.get("lng") is None:
        return None
    return {
        "latitude": float(location["lat"]),
        "longitude": float(location["lng"]),
        "source": "GOOGLE_GEOCODING",
    }


def _route_plan(event, origin_latitude, origin_longitude, api_key):
    if not api_key:
        return {
            "status": "PROVIDER_NOT_CONFIGURED",
            "provider": "GOOGLE_ROUTES",
            "traffic_aware": False,
            "detail": "Google Maps server routing is not configured yet.",
        }

    address = _event_address(event)
    destination = None
    if address:
        destination = {"address": address}
    elif event.latitude is not None and event.longitude is not None:
        destination = {
            "location": {
                "latLng": {
                    "latitude": float(event.latitude),
                    "longitude": float(event.longitude),
                }
            }
        }
    if destination is None:
        return {
            "status": "DESTINATION_REQUIRED",
            "provider": "GOOGLE_ROUTES",
            "traffic_aware": False,
            "detail": "Add an address or coordinates to this event to calculate travel.",
        }

    now = timezone.now()
    arrival_target = event.start_at - timedelta(minutes=int(event.arrival_buffer_minutes or 0))
    provisional_departure = arrival_target - timedelta(minutes=45)
    minimum_departure = now + timedelta(minutes=2)
    departure_time = max(provisional_departure, minimum_departure)

    body = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": float(origin_latitude),
                    "longitude": float(origin_longitude),
                }
            }
        },
        "destination": destination,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": departure_time.isoformat().replace("+00:00", "Z"),
    }
    response = requests.post(
        GOOGLE_ROUTES_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters",
        },
        json=body,
        timeout=10,
    )
    response.raise_for_status()
    routes = response.json().get("routes") or []
    if not routes:
        return {
            "status": "NO_ROUTE",
            "provider": "GOOGLE_ROUTES",
            "traffic_aware": True,
            "detail": "No driving route was returned for this event.",
        }

    route = routes[0]
    duration_seconds = _seconds(route.get("duration"))
    static_seconds = _seconds(route.get("staticDuration"))
    leave_by = arrival_target - timedelta(seconds=duration_seconds)
    return {
        "status": "READY",
        "provider": "GOOGLE_ROUTES",
        "traffic_aware": True,
        "distance_meters": int(route.get("distanceMeters") or 0),
        "duration_seconds": duration_seconds,
        "static_duration_seconds": static_seconds,
        "traffic_delay_seconds": max(0, duration_seconds - static_seconds),
        "arrival_target": arrival_target.isoformat(),
        "leave_by": leave_by.isoformat(),
        "departure_basis": departure_time.isoformat(),
    }


def _weather_risk(short_forecast, precipitation_probability, wind_mph):
    text = str(short_forecast or "").lower()
    severe_words = ("thunder", "storm", "tornado", "hail", "ice", "freezing", "snow", "blizzard")
    if any(word in text for word in severe_words) or wind_mph >= 30 or precipitation_probability >= 70:
        return "HIGH"
    if wind_mph >= 20 or precipitation_probability >= 40 or "rain" in text or "showers" in text:
        return "MODERATE"
    return "LOW"


def _nws_weather(event, destination):
    if not destination:
        return {
            "status": "DESTINATION_COORDINATES_REQUIRED",
            "provider": "NWS",
            "detail": "Destination coordinates are needed for weather intelligence.",
        }
    if str(event.country or "US").upper() != "US":
        return {
            "status": "UNSUPPORTED_REGION",
            "provider": "NWS",
            "detail": "This weather provider currently supports U.S. destinations.",
        }
    now = timezone.now()
    if event.start_at < now - timedelta(hours=1) or event.start_at > now + timedelta(days=7):
        return {
            "status": "OUTSIDE_FORECAST_WINDOW",
            "provider": "NWS",
            "detail": "Hourly destination weather becomes available within about 7 days of the event.",
        }

    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    point_url = NWS_POINTS_URL.format(
        lat=round(float(destination["latitude"]), 4),
        lng=round(float(destination["longitude"]), 4),
    )
    point_response = requests.get(point_url, headers=headers, timeout=8)
    point_response.raise_for_status()
    hourly_url = point_response.json().get("properties", {}).get("forecastHourly")
    if not hourly_url:
        return {"status": "UNAVAILABLE", "provider": "NWS", "detail": "NWS hourly forecast is unavailable for this destination."}

    hourly_response = requests.get(hourly_url, headers=headers, timeout=8)
    hourly_response.raise_for_status()
    periods = hourly_response.json().get("properties", {}).get("periods") or []
    target = event.start_at
    selected = None
    nearest_delta = None
    for period in periods:
        start = period.get("startTime")
        if not start:
            continue
        try:
            period_start = timezone.datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = abs((period_start - target).total_seconds())
        if nearest_delta is None or delta < nearest_delta:
            selected = period
            nearest_delta = delta
    if not selected:
        return {"status": "UNAVAILABLE", "provider": "NWS", "detail": "No matching hourly forecast was returned."}

    precip = (selected.get("probabilityOfPrecipitation") or {}).get("value")
    precip = int(round(float(precip or 0)))
    wind_text = str(selected.get("windSpeed") or "0 mph").split(" ")[0].split("-")[0]
    try:
        wind_mph = int(round(float(wind_text)))
    except ValueError:
        wind_mph = 0
    short_forecast = selected.get("shortForecast") or ""
    risk = _weather_risk(short_forecast, precip, wind_mph)
    return {
        "status": "READY",
        "provider": "NWS",
        "forecast_time": selected.get("startTime"),
        "temperature": selected.get("temperature"),
        "temperature_unit": selected.get("temperatureUnit") or "F",
        "precipitation_probability": precip,
        "wind_speed": selected.get("windSpeed") or "",
        "wind_direction": selected.get("windDirection") or "",
        "short_forecast": short_forecast,
        "risk": risk,
    }


def _recommendation(event, route, weather):
    messages = []
    if route.get("status") == "READY":
        delay_minutes = int(round(route.get("traffic_delay_seconds", 0) / 60))
        if delay_minutes >= 10:
            messages.append(f"Traffic is adding about {delay_minutes} minutes to the drive.")
        messages.append(f"Leave by {route['leave_by']} to arrive {int(event.arrival_buffer_minutes or 0)} minutes early.")
    else:
        messages.append(route.get("detail") or "Travel time is not available yet.")

    if weather.get("status") == "READY":
        risk = weather.get("risk")
        forecast = weather.get("short_forecast") or "Weather available"
        precip = weather.get("precipitation_probability", 0)
        if risk == "HIGH":
            messages.append(f"High weather risk near event time: {forecast} ({precip}% precipitation chance).")
        elif risk == "MODERATE":
            messages.append(f"Watch the weather near event time: {forecast} ({precip}% precipitation chance).")
        else:
            messages.append(f"Weather currently looks low-risk: {forecast}.")
    elif weather.get("detail"):
        messages.append(weather["detail"])
    return messages


def build_travel_plan(event, origin_latitude, origin_longitude):
    if event.status != event.Status.ACTIVE:
        raise TravelAssistError("Travel intelligence is only available for active events.")
    try:
        origin_latitude = float(origin_latitude)
        origin_longitude = float(origin_longitude)
    except (TypeError, ValueError) as exc:
        raise TravelAssistError("Valid device latitude and longitude are required.") from exc
    if not (-90 <= origin_latitude <= 90 and -180 <= origin_longitude <= 180):
        raise TravelAssistError("Device coordinates are outside valid bounds.")

    api_key = _google_key()
    destination = _geocode_destination(event, api_key)
    try:
        route = _route_plan(event, origin_latitude, origin_longitude, api_key)
    except requests.RequestException as exc:
        route = {"status": "PROVIDER_ERROR", "provider": "GOOGLE_ROUTES", "traffic_aware": False, "detail": "Travel provider is temporarily unavailable."}
    try:
        weather = _nws_weather(event, destination)
    except requests.RequestException:
        weather = {"status": "PROVIDER_ERROR", "provider": "NWS", "detail": "Weather provider is temporarily unavailable."}

    return {
        "event_id": event.id,
        "event_title": event.title,
        "event_start_at": event.start_at.isoformat(),
        "destination": {
            "label": event.location_name or _event_address(event),
            "address": _event_address(event),
            "coordinates_available": bool(destination),
        },
        "arrival_buffer_minutes": int(event.arrival_buffer_minutes or 0),
        "route": route,
        "weather": weather,
        "recommendations": _recommendation(event, route, weather),
        "generated_at": timezone.now().isoformat(),
    }
