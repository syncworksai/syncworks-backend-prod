from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from personal_calendar.models import PersonalCalendarEvent


def _travel_context(event: PersonalCalendarEvent) -> dict[str, Any]:
    metadata = event.metadata or {}
    plan = metadata.get("travel_assist") or {}
    monitor = metadata.get("travel_monitor") or {}
    route = plan.get("route") or {}
    weather = plan.get("weather") or {}
    alert = monitor.get("last_alert") or None
    return {
        "monitoring_enabled": bool(monitor.get("enabled")),
        "last_checked_at": monitor.get("last_checked_at"),
        "leave_by": route.get("leave_by"),
        "drive_minutes": int(round(float(route.get("duration_seconds") or 0) / 60)) if route.get("status") == "READY" else None,
        "traffic_delay_minutes": int(round(float(route.get("traffic_delay_seconds") or 0) / 60)) if route.get("status") == "READY" else None,
        "weather": {
            "status": weather.get("status"),
            "risk": weather.get("risk"),
            "forecast": weather.get("short_forecast"),
            "precipitation_probability": weather.get("precipitation_probability"),
            "temperature": weather.get("temperature"),
            "temperature_unit": weather.get("temperature_unit"),
        } if weather else None,
        "alert": {
            "severity": alert.get("severity"),
            "messages": list(alert.get("messages") or [])[:4],
            "created_at": alert.get("created_at"),
        } if alert else None,
    }


def _event_row(event: PersonalCalendarEvent) -> dict[str, Any]:
    start = timezone.localtime(event.start_at)
    end = timezone.localtime(event.end_at) if event.end_at else None
    ready_by = start - timedelta(minutes=int(event.arrival_buffer_minutes or 0))
    has_location = bool(event.location_name or event.address_line1 or event.city or event.postal_code)
    return {
        "id": event.id,
        "title": str(event.title or "")[:160],
        "start_at": start.isoformat(),
        "end_at": end.isoformat() if end else None,
        "all_day": bool(event.all_day),
        "source": event.source,
        "location": {
            "name": str(event.location_name or "")[:160],
            "city": str(event.city or "")[:100],
            "state": str(event.state or "")[:80],
            "postal_code": str(event.postal_code or "")[:20],
            "has_location": has_location,
        },
        "arrival_buffer_minutes": int(event.arrival_buffer_minutes or 0),
        "reminder_minutes": int(event.reminder_minutes or 0),
        "ready_by": ready_by.isoformat(),
        "travel": _travel_context(event),
    }


def _overlap(a: PersonalCalendarEvent, b: PersonalCalendarEvent) -> bool:
    a_end = a.end_at or a.start_at
    b_end = b.end_at or b.start_at
    return a.start_at < b_end and b.start_at < a_end


def build_sync_calendar_context(user) -> dict[str, Any]:
    now = timezone.now()
    local_now = timezone.localtime(now)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    horizon = now + timedelta(days=7)

    events = list(
        PersonalCalendarEvent.objects.filter(
            owner=user,
            status=PersonalCalendarEvent.Status.ACTIVE,
            start_at__gte=now - timedelta(hours=12),
            start_at__lte=horizon,
        ).order_by("start_at", "id")[:80]
    )
    upcoming = [event for event in events if event.start_at >= now]
    today = [event for event in events if today_start <= timezone.localtime(event.start_at) < tomorrow_start]

    conflicts: list[dict[str, Any]] = []
    for index, event in enumerate(upcoming):
        for other in upcoming[index + 1 :]:
            if other.start_at > (event.end_at or event.start_at):
                break
            if _overlap(event, other):
                conflicts.append({
                    "first_event_id": event.id,
                    "first_title": str(event.title or "")[:100],
                    "second_event_id": other.id,
                    "second_title": str(other.title or "")[:100],
                })
            if len(conflicts) >= 5:
                break
        if len(conflicts) >= 5:
            break

    next_event = upcoming[0] if upcoming else None
    attention: list[dict[str, Any]] = []
    if conflicts:
        attention.append({"code": "CALENDAR_CONFLICT", "count": len(conflicts)})
    if next_event:
        minutes_until = max(0, int((next_event.start_at - now).total_seconds() // 60))
        if minutes_until <= 120:
            attention.append({"code": "UPCOMING_EVENT", "minutes_until": minutes_until, "title": str(next_event.title or "")[:100]})
        if (next_event.location_name or next_event.address_line1 or next_event.city) and next_event.arrival_buffer_minutes == 0:
            attention.append({"code": "LOCATION_WITHOUT_ARRIVAL_BUFFER", "event_id": next_event.id})
        travel = _travel_context(next_event)
        if travel.get("alert"):
            attention.append({
                "code": "TRAVEL_CHANGE",
                "event_id": next_event.id,
                "severity": travel["alert"].get("severity"),
                "messages": travel["alert"].get("messages"),
            })
        weather = travel.get("weather") or {}
        if weather.get("risk") == "HIGH":
            attention.append({
                "code": "WEATHER_RISK",
                "event_id": next_event.id,
                "forecast": weather.get("forecast"),
                "precipitation_probability": weather.get("precipitation_probability"),
            })

    next_travel = _travel_context(next_event) if next_event else None
    return {
        "available": True,
        "as_of": local_now.isoformat(),
        "today": {"count": len(today), "events": [_event_row(event) for event in today[:8]]},
        "next_event": _event_row(next_event) if next_event else None,
        "next_7_days_count": len(upcoming),
        "conflicts": conflicts,
        "attention": attention,
        "travel_time": {
            "available": bool(next_travel and next_travel.get("drive_minutes") is not None),
            "next_event": next_travel,
            "note": "Live traffic is only reported when a real provider result is available.",
        },
    }
