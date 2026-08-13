from datetime import timedelta, timezone as dt_timezone

import requests
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import PersonalCalendarEvent


def aware(value):
    parsed = parse_datetime(value) if value else None
    if not parsed:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, dt_timezone.utc)


def import_events(user, connection, access_token):
    count = 0
    headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'outlook.timezone="UTC"'}
    start = (timezone.now() - timedelta(days=30)).isoformat()
    end = (timezone.now() + timedelta(days=365)).isoformat()
    for calendar in connection.get("calendars") or []:
        if not calendar.get("selected", True):
            continue
        calendar_id = str(calendar.get("id") or "")
        if not calendar_id:
            continue
        response = requests.get("https://graph.microsoft.com/v1.0/me/calendars/" + requests.utils.quote(calendar_id, safe="") + "/calendarView", headers=headers, params={"startDateTime": start, "endDateTime": end, "$top": 1000}, timeout=45)
        response.raise_for_status()
        for remote in response.json().get("value") or []:
            remote_id = remote.get("id")
            start_data = remote.get("start") or {}
            start_at = aware(start_data.get("dateTime"))
            if not remote_id or not start_at:
                continue
            event, _ = PersonalCalendarEvent.objects.get_or_create(owner=user, source="OUTLOOK", external_calendar_id=calendar_id, external_event_id=str(remote_id), defaults={"title": remote.get("subject") or "Calendar event", "start_at": start_at})
            event.title = remote.get("subject") or "Calendar event"
            event.description = remote.get("bodyPreview") or ""
            event.start_at = start_at
            event.end_at = aware((remote.get("end") or {}).get("dateTime"))
            event.all_day = bool(remote.get("isAllDay"))
            event.location_name = (remote.get("location") or {}).get("displayName") or ""
            event.timezone = start_data.get("timeZone") or event.timezone
            event.status = "CANCELLED" if remote.get("isCancelled") else "ACTIVE"
            event.metadata = {**(event.metadata or {}), "provider": "MICROSOFT", "account": connection.get("email", ""), "remote_updated": remote.get("lastModifiedDateTime", "")}
            event.save()
            count += 1
    return count
