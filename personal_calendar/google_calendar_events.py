from datetime import datetime, time, timedelta, timezone as dt_timezone

import requests
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import PersonalCalendarEvent


def _event_datetime(value, date_value=None):
    parsed = parse_datetime(value) if value else None
    if parsed is not None:
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, dt_timezone.utc)
    parsed_date = parse_date(date_value) if date_value else None
    if parsed_date is not None:
        return timezone.make_aware(datetime.combine(parsed_date, time.min), dt_timezone.utc)
    return None


def import_events(user, connection, access_token):
    count = 0
    headers = {"Authorization": f"Bearer {access_token}"}
    start = (timezone.now() - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    end = (timezone.now() + timedelta(days=365)).isoformat().replace("+00:00", "Z")
    for calendar in connection.get("calendars") or []:
        if not calendar.get("selected", True):
            continue
        calendar_id = str(calendar.get("id") or "")
        if not calendar_id:
            continue
        response = requests.get(
            "https://www.googleapis.com/calendar/v3/calendars/" + requests.utils.quote(calendar_id, safe="") + "/events",
            headers=headers,
            params={"timeMin": start, "timeMax": end, "singleEvents": "true", "showDeleted": "true", "maxResults": 2500},
            timeout=45,
        )
        response.raise_for_status()
        for remote in response.json().get("items") or []:
            remote_id = remote.get("id")
            start_data = remote.get("start") or {}
            end_data = remote.get("end") or {}
            start_at = _event_datetime(start_data.get("dateTime"), start_data.get("date"))
            if not remote_id or not start_at:
                continue
            end_at = _event_datetime(end_data.get("dateTime"), end_data.get("date"))
            event, _ = PersonalCalendarEvent.objects.get_or_create(
                owner=user,
                source="GOOGLE",
                external_calendar_id=calendar_id,
                external_event_id=str(remote_id),
                defaults={"title": remote.get("summary") or "Calendar event", "start_at": start_at},
            )
            event.title = remote.get("summary") or "Calendar event"
            event.description = remote.get("description") or ""
            event.start_at = start_at
            event.end_at = end_at
            event.all_day = bool(start_data.get("date") and not start_data.get("dateTime"))
            event.location_name = remote.get("location") or ""
            event.timezone = start_data.get("timeZone") or calendar.get("timezone") or event.timezone
            event.status = "CANCELLED" if remote.get("status") == "cancelled" else "ACTIVE"
            event.metadata = {**(event.metadata or {}), "provider": "GOOGLE", "account": connection.get("email", ""), "remote_updated": remote.get("updated", "")}
            event.save()
            count += 1
    return count
