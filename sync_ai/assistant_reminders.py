from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import Notification

from .jarvis_product import live_access, load_profile
from .live_travel import leave_plan, route_minutes


def _clock(value):
    local = timezone.localtime(value)
    return local.strftime("%I:%M %p").lstrip("0")


def _departure_alerts_enabled(profile):
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    proactive = modules.get("sync_proactive") if isinstance(modules.get("sync_proactive"), dict) else {}
    return proactive.get("enabled", True) is not False and proactive.get("departure_alerts", True) is not False


def process_departure_reminders() -> dict:
    now = timezone.now()
    scanned = sent = skipped = 0
    events = PersonalCalendarEvent.objects.select_related("owner").filter(
        status="ACTIVE",
        start_at__gt=now,
        start_at__lte=now + timedelta(hours=24),
    )
    for event in events.iterator():
        metadata = dict(event.metadata or {})
        if not metadata.get("sync_departure_reminder_enabled") or metadata.get("sync_departure_reminder_sent_at"):
            continue
        scanned += 1
        _, profile = load_profile(event.owner)
        if not live_access(event.owner, profile) or not _departure_alerts_enabled(profile):
            skipped += 1
            continue
        home = profile.get("home_location") or {}
        destination = {"latitude": event.latitude, "longitude": event.longitude}
        travel = route_minutes(home, destination)
        if not travel.get("available") and metadata.get("travel_minutes") not in (None, ""):
            try:
                travel = {"available": True, "minutes": max(1, int(metadata.get("travel_minutes"))), "traffic_aware": False}
            except (TypeError, ValueError):
                pass
        live = profile.get("live") or {}
        departure = leave_plan(
            event_start=event.start_at,
            arrival_buffer_minutes=int(event.arrival_buffer_minutes or live.get("arrival_buffer_minutes") or 0),
            reminder_minutes=int(event.reminder_minutes if event.reminder_minutes is not None else live.get("departure_reminder_minutes") or 10),
            travel=travel,
        )
        if not departure.get("available"):
            skipped += 1
            continue
        remind_at = datetime.fromisoformat(departure["remind_at"])
        leave_by = datetime.fromisoformat(departure["leave_by"])
        if remind_at <= now <= event.start_at:
            location = event.location_name or event.address_line1 or "your event"
            Notification.objects.create(
                recipient=event.owner,
                type=Notification.TYPE_REMINDER,
                title=f"Time to leave soon: {event.title}",
                body=f"Plan to leave by {_clock(leave_by)} for {location}. Estimated drive time is {departure.get('travel_minutes')} minutes.",
                data={
                    "kind": "SYNC_ASSISTANT_DEPARTURE",
                    "event_id": event.id,
                    "leave_by": departure["leave_by"],
                    "travel_minutes": departure.get("travel_minutes"),
                    "traffic_aware": departure.get("traffic_aware"),
                    "url": "/customer/calendar",
                },
            )
            metadata["sync_departure_reminder_sent_at"] = now.isoformat()
            metadata["sync_departure_leave_by"] = departure["leave_by"]
            metadata["sync_departure_travel_minutes"] = departure.get("travel_minutes")
            event.metadata = metadata
            event.save(update_fields=["metadata", "updated_at"])
            sent += 1
    return {"scanned": scanned, "sent": sent, "skipped": skipped}
