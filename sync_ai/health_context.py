from __future__ import annotations

from typing import Any

from django.utils import timezone

from customer_health.models import CustomerHealthProfile


def _text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "completed", "done"}


def _remaining(current: Any, goal: Any) -> float | None:
    current_value = _number(current)
    goal_value = _number(goal)
    if current_value is None or goal_value is None:
        return None
    return round(max(0.0, goal_value - current_value), 2)


def _percent(current: Any, goal: Any) -> float | None:
    current_value = _number(current)
    goal_value = _number(goal)
    if current_value is None or goal_value in (None, 0):
        return None
    return round(max(0.0, min(100.0, (current_value / goal_value) * 100.0)), 1)


def _coalesce(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _today_plan(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    week_plan = snapshot.get("week_plan")
    if not isinstance(week_plan, list):
        return None

    today = timezone.localdate().isoformat()
    for item in week_plan:
        if not isinstance(item, dict) or _text(item.get("ymd"), 20) != today:
            continue
        return {
            "workout_name": _text(item.get("workout_name") or item.get("name"), 120),
            "time": _text(item.get("time"), 20),
            "status": _text(item.get("status"), 40),
            "duration_minutes": _number(item.get("duration_minutes")),
            "note": _text(item.get("note"), 180),
        }
    return None


def _recent_workouts(history: list[Any], limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in reversed(history[-20:]):
        if not isinstance(item, dict):
            continue
        row = {
            "workout_name": _text(item.get("workout_name") or item.get("name") or item.get("title"), 120),
            "completed_at": _text(item.get("completed_at") or item.get("ended_at") or item.get("date"), 40),
            "duration_minutes": _number(item.get("duration_minutes") or item.get("active_minutes")),
            "rpe": _number(item.get("rpe") or item.get("average_rpe")),
        }
        if any(value not in (None, "") for value in row.values()):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def build_sync_health_context(user) -> dict[str, Any]:
    """Return compact, user-scoped wellness context for SYNC.

    The full Health JSON can contain detailed session history. SYNC receives only the
    current decision signals and a few recent workout summaries, never the raw payload.
    """
    health = CustomerHealthProfile.objects.filter(user=user).first()
    if health is None:
        return {"available": False}

    profile = health.profile_json if isinstance(health.profile_json, dict) else {}
    snapshot = health.snapshot_json if isinstance(health.snapshot_json, dict) else {}
    history = health.history_json if isinstance(health.history_json, list) else []
    workouts = health.workouts_json if isinstance(health.workouts_json, list) else []
    progress = health.progress_json if isinstance(health.progress_json, list) else []

    protein_now = _coalesce(snapshot, "protein_today", "protein")
    protein_goal = _coalesce(snapshot, "protein_goal") or profile.get("protein_goal")
    steps_now = snapshot.get("steps")
    steps_goal = _coalesce(snapshot, "step_goal", "steps_goal")
    water_now = snapshot.get("water")
    water_goal = snapshot.get("water_goal")
    calories_now = snapshot.get("calories")
    calories_goal = _coalesce(snapshot, "calorie_goal", "calories_goal")
    sleep_hours = _coalesce(snapshot, "last_sleep_hours", "sleep_hours")

    readiness = _text(snapshot.get("readiness"), 80)
    soreness_areas = snapshot.get("soreness_areas")
    if isinstance(soreness_areas, list):
        soreness_areas = [_text(item, 60) for item in soreness_areas[:8] if _text(item, 60)]
    else:
        soreness_areas = _text(soreness_areas, 180)

    attention: list[dict[str, Any]] = []
    protein_remaining = _remaining(protein_now, protein_goal)
    steps_remaining = _remaining(steps_now, steps_goal)
    water_remaining = _remaining(water_now, water_goal)

    if protein_remaining and protein_remaining > 0:
        attention.append({"code": "PROTEIN_REMAINING", "remaining": protein_remaining})
    if steps_remaining and steps_remaining > 0:
        attention.append({"code": "STEPS_REMAINING", "remaining": steps_remaining})
    if water_remaining and water_remaining > 0:
        attention.append({"code": "WATER_REMAINING", "remaining": water_remaining})
    if sleep_hours is None:
        attention.append({"code": "SLEEP_NOT_RECORDED"})
    if soreness_areas or _text(snapshot.get("soreness_notes"), 180):
        attention.append({"code": "SORENESS_RECORDED"})

    return {
        "available": True,
        "updated_at": health.updated_at.isoformat() if health.updated_at else None,
        "goals": {
            "primary_goal": _text(profile.get("primary_goal") or snapshot.get("goal"), 100),
            "goal_detail": _text(profile.get("goal_detail"), 180),
            "nutrition_focus": _text(profile.get("nutrition_focus"), 120),
            "training_days_per_week": _number(profile.get("training_days")),
            "preferred_workout_time": _text(profile.get("preferred_time"), 80),
        },
        "readiness": {
            "status": readiness,
            "notes": _text(snapshot.get("readiness_notes"), 180),
            "soreness_areas": soreness_areas,
            "soreness_notes": _text(snapshot.get("soreness_notes"), 180),
            "sleep_hours": _number(sleep_hours),
        },
        "today": {
            "planned_workout": _today_plan(snapshot),
            "workout_completed": _bool(snapshot.get("workout_completed_today")),
            "time_available": _text(snapshot.get("time_available"), 80),
            "equipment": _text(snapshot.get("equipment"), 100),
            "steps": _number(steps_now),
            "step_goal": _number(steps_goal),
            "steps_percent": _percent(steps_now, steps_goal),
            "protein_grams": _number(protein_now),
            "protein_goal_grams": _number(protein_goal),
            "protein_percent": _percent(protein_now, protein_goal),
            "calories": _number(calories_now),
            "calorie_goal": _number(calories_goal),
            "water": _number(water_now),
            "water_goal": _number(water_goal),
            "meals_logged": _number(snapshot.get("meals_logged_today")),
        },
        "weekly": {
            "completed_workouts": _number(_coalesce(snapshot, "weekly_completed", "completed_workouts")),
            "planned_workouts": _number(snapshot.get("planned_workouts")),
        },
        "recent_workouts": _recent_workouts(history),
        "counts": {
            "saved_workouts": len(workouts),
            "history_entries": len(history),
            "progress_entries": len(progress),
        },
        "attention": attention[:8],
    }
