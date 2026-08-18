from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import PersonalCalendarEvent
from .travel_assist import TravelAssistError, build_travel_plan


def _minutes(value):
    try:
        return int(round(float(value or 0) / 60))
    except (TypeError, ValueError):
        return 0


def _changed_alert(previous: dict, current: dict) -> dict | None:
    previous_route = (previous or {}).get("route") or {}
    current_route = (current or {}).get("route") or {}
    previous_weather = (previous or {}).get("weather") or {}
    current_weather = (current or {}).get("weather") or {}

    alerts = []
    old_delay = _minutes(previous_route.get("traffic_delay_seconds"))
    new_delay = _minutes(current_route.get("traffic_delay_seconds"))
    if current_route.get("status") == "READY" and new_delay - old_delay >= 10:
        alerts.append(f"Traffic added about {new_delay - old_delay} more minutes since the last check.")

    old_leave = previous_route.get("leave_by")
    new_leave = current_route.get("leave_by")
    if old_leave and new_leave:
        try:
            old_dt = timezone.datetime.fromisoformat(str(old_leave).replace("Z", "+00:00"))
            new_dt = timezone.datetime.fromisoformat(str(new_leave).replace("Z", "+00:00"))
            shift = int(round((old_dt - new_dt).total_seconds() / 60))
            if shift >= 10:
                alerts.append(f"Leave {shift} minutes earlier than the prior plan.")
        except ValueError:
            pass

    risk_rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
    old_risk = str(previous_weather.get("risk") or "LOW").upper()
    new_risk = str(current_weather.get("risk") or "LOW").upper()
    if risk_rank.get(new_risk, 0) > risk_rank.get(old_risk, 0):
        alerts.append(f"Weather risk increased from {old_risk.lower()} to {new_risk.lower()}.")

    if not alerts:
        return None
    return {
        "severity": "HIGH" if new_risk == "HIGH" or new_delay >= 20 else "MEDIUM",
        "messages": alerts,
        "created_at": timezone.now().isoformat(),
    }


def enable_trip_monitoring(event: PersonalCalendarEvent, latitude, longitude) -> dict:
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise TravelAssistError("Valid latitude and longitude are required to monitor this trip.") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise TravelAssistError("Trip origin coordinates are outside valid bounds.")

    metadata = dict(event.metadata or {})
    metadata["travel_monitor"] = {
        "enabled": True,
        "origin": {"latitude": latitude, "longitude": longitude},
        "enabled_at": timezone.now().isoformat(),
        "last_checked_at": None,
        "last_alert": None,
    }
    event.metadata = metadata
    event.save(update_fields=("metadata", "updated_at"))
    return metadata["travel_monitor"]


def disable_trip_monitoring(event: PersonalCalendarEvent) -> dict:
    metadata = dict(event.metadata or {})
    monitor = dict(metadata.get("travel_monitor") or {})
    monitor["enabled"] = False
    monitor["disabled_at"] = timezone.now().isoformat()
    metadata["travel_monitor"] = monitor
    event.metadata = metadata
    event.save(update_fields=("metadata", "updated_at"))
    return monitor


def refresh_monitored_trip(event: PersonalCalendarEvent) -> dict:
    metadata = dict(event.metadata or {})
    monitor = dict(metadata.get("travel_monitor") or {})
    origin = monitor.get("origin") or {}
    if not monitor.get("enabled"):
        return {"status": "SKIPPED", "detail": "Trip monitoring is disabled."}
    if origin.get("latitude") is None or origin.get("longitude") is None:
        return {"status": "SKIPPED", "detail": "Trip monitoring has no saved origin."}

    previous = metadata.get("travel_assist") or {}
    plan = build_travel_plan(event, origin["latitude"], origin["longitude"])
    alert = _changed_alert(previous, plan)
    monitor["last_checked_at"] = timezone.now().isoformat()
    if alert:
        monitor["last_alert"] = alert
    metadata["travel_assist"] = plan
    metadata["travel_monitor"] = monitor
    event.metadata = metadata
    event.save(update_fields=("metadata", "updated_at"))
    return {"status": "UPDATED", "alert": alert, "plan": plan}


def refresh_due_trip_monitors(*, limit=100, now=None) -> dict:
    now = now or timezone.now()
    events = PersonalCalendarEvent.objects.filter(
        status=PersonalCalendarEvent.Status.ACTIVE,
        start_at__gte=now - timedelta(minutes=15),
        start_at__lte=now + timedelta(hours=24),
    ).order_by("start_at", "id")[:limit]

    counts = {"checked": 0, "alerts": 0, "skipped": 0, "failed": 0}
    for event in events:
        monitor = (event.metadata or {}).get("travel_monitor") or {}
        if not monitor.get("enabled"):
            counts["skipped"] += 1
            continue
        last_checked = monitor.get("last_checked_at")
        if last_checked:
            try:
                parsed = timezone.datetime.fromisoformat(str(last_checked).replace("Z", "+00:00"))
                minutes_until_event = max(0, (event.start_at - now).total_seconds() / 60)
                cadence = 5 if minutes_until_event <= 120 else 15
                if parsed > now - timedelta(minutes=cadence):
                    counts["skipped"] += 1
                    continue
            except ValueError:
                pass
        try:
            result = refresh_monitored_trip(event)
        except TravelAssistError:
            counts["failed"] += 1
            continue
        counts["checked"] += 1
        if result.get("alert"):
            counts["alerts"] += 1
    return counts
