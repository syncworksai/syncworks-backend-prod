from datetime import timedelta

import requests
from django.utils import timezone

from .models import PersonalCalendarEvent


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
            start_at = start_data.get("dateTime")
            if not remote_id or not start_at:
                continue
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
            event.end_at = (remote.get("end") or {}).get("dateTime")
            event.location_name = remote.get("location") or ""
            event.timezone = start_data.get("timeZone") or calendar.get("timezone") or event.timezone
            event.status = "CANCELLED" if remote.get("status") == "cancelled" else "ACTIVE"
            event.metadata = {**(event.metadata or {}), "provider": "GOOGLE", "account": connection.get("email", "")}
            event.save()
            count += 1
    return count
