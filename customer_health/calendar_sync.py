from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_calendar.models import PersonalCalendarEvent


def _time_value(value) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) >= 5 and raw[2] == ":" and raw[:2].isdigit() and raw[3:5].isdigit():
        return raw[:5]
    if "morning" in raw:
        return "07:00"
    if "afternoon" in raw:
        return "13:00"
    if "evening" in raw:
        return "18:00"
    return "18:00"


def sync_health_plan_to_calendar(profile) -> None:
    snapshot = profile.snapshot_json if isinstance(profile.snapshot_json, dict) else {}
    plan = snapshot.get("week_plan") if isinstance(snapshot.get("week_plan"), list) else []
    profile_data = profile.profile_json if isinstance(profile.profile_json, dict) else {}
    timezone_name = str(profile_data.get("timezone") or snapshot.get("timezone") or "America/Chicago")
    try:
        event_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone_name = "America/Chicago"
        event_zone = ZoneInfo(timezone_name)

    active_ids = []
    for index, item in enumerate(plan):
        if not isinstance(item, dict) or not item.get("ymd") or not (item.get("workout_name") or item.get("name")):
            continue
        health_id = str(item.get("id") or f"{item.get('ymd')}-{index}")[:255]
        if str(item.get("status") or "").strip().lower() in {"skipped", "rescheduled", "cancelled", "canceled"}:
            continue
        try:
            start = datetime.fromisoformat(f"{item['ymd']}T{_time_value(item.get('time'))}:00").replace(tzinfo=event_zone)
        except (TypeError, ValueError):
            continue
        try:
            duration = max(10, min(int(float(item.get("duration_minutes") or item.get("duration") or 45)), 360))
        except (TypeError, ValueError):
            duration = 45
        exercises = item.get("exercises") if isinstance(item.get("exercises"), list) else []
        metadata = {
            "health_plan_id": health_id,
            "health_status": str(item.get("status") or "Planned"),
            "focus": str(item.get("focus") or ""),
            "exercise_count": len(exercises),
            "calendar_owner": "HEALTH",
            "deep_link": "/customer/health",
        }
        PersonalCalendarEvent.objects.update_or_create(
            owner=profile.user,
            source=PersonalCalendarEvent.Source.HEALTH,
            external_calendar_id="health-plan",
            external_event_id=health_id,
            defaults={
                "title": str(item.get("workout_name") or item.get("name"))[:180],
                "description": str(item.get("note") or "Scheduled workout"),
                "start_at": start,
                "end_at": start + timedelta(minutes=duration),
                "timezone": timezone_name,
                "status": PersonalCalendarEvent.Status.ACTIVE,
                "metadata": metadata,
            },
        )
        active_ids.append(health_id)

    PersonalCalendarEvent.objects.filter(
        owner=profile.user,
        source=PersonalCalendarEvent.Source.HEALTH,
        external_calendar_id="health-plan",
    ).exclude(external_event_id__in=active_ids).update(status=PersonalCalendarEvent.Status.ARCHIVED)
