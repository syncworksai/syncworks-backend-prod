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


def sync_nutrition_plan_to_calendar(profile) -> list[str]:
    snapshot = profile.snapshot_json if isinstance(profile.snapshot_json, dict) else {}
    plan = snapshot.get("nutrition_week_plan")
    if not isinstance(plan, list):
        return []
    data = profile.profile_json if isinstance(profile.profile_json, dict) else {}
    zone_name = str(data.get("timezone") or snapshot.get("timezone") or "America/Chicago")
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        zone_name = "America/Chicago"
        zone = ZoneInfo(zone_name)
    ids = []
    for meal in plan:
        if not isinstance(meal, dict) or not meal.get("id") or not meal.get("name"):
            continue
        if str(meal.get("status", "")).lower() in {"cancelled", "canceled", "skipped"}:
            continue
        try:
            start = datetime.fromisoformat(f"{meal['ymd']}T{_time_value(meal.get('time'))}:00").replace(tzinfo=zone)
        except (KeyError, TypeError, ValueError):
            continue
        meal_id = str(meal["id"])[:255]
        PersonalCalendarEvent.objects.update_or_create(
            owner=profile.user, source=PersonalCalendarEvent.Source.HEALTH,
            external_calendar_id="nutrition-plan", external_event_id=meal_id,
            defaults={"title": ("Nutrition: " + str(meal.get("meal_type", "Meal")).title())[:180],
                      "description": str(meal["name"]), "start_at": start,
                      "end_at": start + timedelta(minutes=30), "timezone": zone_name,
                      "status": PersonalCalendarEvent.Status.ACTIVE,
                      "metadata": {"calendar_owner": "HEALTH", "meal_plan_id": meal_id,
                                   "activity_type": "nutrition", "deep_link": "/customer/health"}},
        )
        ids.append(meal_id)
    PersonalCalendarEvent.objects.filter(owner=profile.user, source=PersonalCalendarEvent.Source.HEALTH,
        external_calendar_id="nutrition-plan").exclude(external_event_id__in=ids).update(status=PersonalCalendarEvent.Status.ARCHIVED)
    return list(PersonalCalendarEvent.objects.filter(owner=profile.user, source=PersonalCalendarEvent.Source.HEALTH,
        external_calendar_id="nutrition-plan", status=PersonalCalendarEvent.Status.ACTIVE,
        external_event_id__in=ids).values_list("external_event_id", flat=True))
