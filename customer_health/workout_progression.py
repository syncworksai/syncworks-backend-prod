"""Read-only, per-user workout trends and conservative progression suggestions."""
from __future__ import annotations

from collections import defaultdict

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CustomerHealthProfile


def _number(value):
    try:
        number = float(value)
        return number if 0 <= number < 100000 else None
    except (TypeError, ValueError):
        return None


def _exercise_name(exercise):
    return str(exercise.get("substitute_name") or exercise.get("name") or exercise.get("exercise_name") or "").strip()


def _working_sets(exercise):
    rows = exercise.get("set_logs")
    if not isinstance(rows, list):
        rows = exercise.get("sets", [])
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("set_type", "working")).lower() == "warmup":
            continue
        if row.get("completed") is False or row.get("status") in ("skipped", "planned"):
            continue
        reps = _number(row.get("actual_reps", row.get("reps")))
        weight = _number(row.get("actual_weight", row.get("weight", row.get("load"))))
        if reps is None or reps < 1:
            continue
        cleaned.append({
            "reps": int(reps),
            "weight": weight,
            "rpe": _number(row.get("rpe")),
            "pain": _number(row.get("pain_score")),
            "poor_form": str(row.get("form_quality", "")).lower() == "poor",
            "failure": bool(row.get("reached_failure")),
        })
    return cleaned


def build_profile_progression(history, profile):
    sessions = [row for row in (history or []) if isinstance(row, dict) and
                str(row.get("status", "completed")).lower() not in ("active", "cancelled", "canceled", "planned")]
    sessions.sort(key=lambda row: str(row.get("finished_at") or row.get("completed_at") or row.get("updated_at") or ""))
    by_exercise = defaultdict(list)
    for session in sessions:
        for exercise in session.get("exercises", []):
            if not isinstance(exercise, dict):
                continue
            name = _exercise_name(exercise)
            sets = _working_sets(exercise)
            if name and sets:
                by_exercise[name.casefold()].append((name, sets))
    goal = str((profile or {}).get("primary_goal") or (profile or {}).get("goal") or "").lower()
    if "endur" in goal:
        bounds = (12, 15)
    elif "strength" in goal or "power" in goal:
        bounds = (5, 8)
    else:
        bounds = (8, 12)
    exercises = []
    for key, rows in sorted(by_exercise.items()):
        name, last_sets = rows[-1]
        current = last_sets[-1]
        weights = [row["weight"] for row in last_sets if row["weight"] is not None]
        effort = [row["rpe"] for row in last_sets if row["rpe"] is not None]
        high_pain = any((row["pain"] or 0) >= 2 or row["poor_form"] for row in last_sets)
        failure = any(row["failure"] for row in last_sets)
        hard = failure or (effort and max(effort) >= 9)
        all_at_top = all(row["reps"] >= bounds[1] for row in last_sets)
        low_effort = bool(effort) and max(effort) <= 8
        weight = current["weight"]
        next_weight = weight
        if high_pain:
            action, reason = "review", "Pain or form concern recorded: do not increase. Review or substitute the movement."
        elif hard:
            action, reason = "hold", "High effort or failure recorded. Repeat or reduce and prioritize technique."
        elif all_at_top and low_effort and weight is not None and weight > 0:
            action, reason = "increase", "All working sets reached the top of the rep range with controlled effort."
            increment = 2.5 if weight < 50 else 5
            next_weight = round((weight + increment) / 2.5) * 2.5
        else:
            action, reason = "repeat", "Build consistent clean reps through the suggested range before adding load."
        exercises.append({
            "exercise": name,
            "sessions_logged": len(rows),
            "last_sets": len(last_sets),
            "last_weight": weight,
            "last_reps": current["reps"],
            "best_logged_weight": max((s["weight"] for _, sets in rows for s in sets if s["weight"] is not None), default=None),
            "rep_range": {"min": bounds[0], "max": bounds[1]},
            "suggested_weight": next_weight if action != "review" else None,
            "action": action,
            "reason": reason,
            "confidence": "history_based" if len(rows) >= 2 else "limited_history",
        })
    return {
        "workouts_logged": len(sessions),
        "exercises_tracked": len(exercises),
        "goal": goal or None,
        "unit": "as_logged",
        "exercises": exercises,
        "note": "Suggestions depend on logged reps, load, effort and pain. No weight is invented for a new exercise. Confirm units and use controlled form.",
    }


class HealthWorkoutProgressionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = CustomerHealthProfile.objects.get_or_create(user=request.user)
        payload = build_profile_progression(profile.history_json, profile.profile_json)
        return Response(payload)
