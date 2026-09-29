from collections import Counter
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.audit import AuditLog


USAGE_PREFIX = "SYNC_USAGE"
ALLOWED_AREAS = {
    "CALENDAR",
    "SYNC",
    "HEALTH",
    "FINANCE",
    "PROJECTS",
    "SERVICES",
    "SOCIAL",
    "MARKETPLACE",
    "PERSONAL",
}
ALLOWED_METADATA_KEYS = {
    "category",
    "scheduling_mode",
    "source",
    "completed",
    "batch",
    "voice",
    "carplay_ready",
}


def _clean_token(value, maximum=64):
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum() or ch in {"_", "-"})[:maximum]


def _safe_metadata(value):
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for key in ALLOWED_METADATA_KEYS:
        if key not in value:
            continue
        item = value.get(key)
        if isinstance(item, bool):
            cleaned[key] = item
        elif item is not None:
            cleaned[key] = str(item)[:64]
    return cleaned


def _usage_rows(user, days=30):
    since = timezone.now() - timedelta(days=days)
    return AuditLog.objects.filter(
        actor=user,
        action__startswith=f"{USAGE_PREFIX}:",
        created_at__gte=since,
    ).order_by("-created_at")


def build_usage_summary(user, days=30):
    rows = list(_usage_rows(user, days=days))
    active_days = len({row.created_at.date() for row in rows})
    areas = Counter()
    actions = Counter()
    completed = 0
    for row in rows:
        parts = str(row.action or "").split(":", 2)
        if len(parts) == 3:
            areas[parts[1]] += 1
            actions[parts[2]] += 1
        if bool((row.metadata or {}).get("completed")):
            completed += 1

    area_count = len(areas)
    action_count = len(rows)
    score = min(
        100,
        round(
            min(active_days / 12, 1) * 40
            + min(action_count / 30, 1) * 30
            + min(area_count / 5, 1) * 20
            + min(completed / 5, 1) * 10
        ),
    )
    if score >= 80:
        level = "POWER_USER"
    elif score >= 55:
        level = "ACTIVE"
    elif score >= 30:
        level = "BUILDING"
    else:
        level = "GETTING_STARTED"

    return {
        "period_days": days,
        "score": score,
        "level": level,
        "active_days": active_days,
        "action_count": action_count,
        "module_count": area_count,
        "completed_actions": completed,
        "top_areas": [{"area": area, "count": count} for area, count in areas.most_common(5)],
        "top_actions": [{"action": action, "count": count} for action, count in actions.most_common(5)],
    }


def build_platform_usage_summary(days=30):
    since = timezone.now() - timedelta(days=days)
    rows = list(
        AuditLog.objects.filter(
            actor__isnull=False,
            action__startswith=f"{USAGE_PREFIX}:",
            created_at__gte=since,
        ).only("actor_id", "action", "metadata", "created_at")
    )
    areas = Counter()
    actions = Counter()
    categories = Counter()
    active_users_7d = set()
    tracked_users = set()
    completed = 0
    seven_days_ago = timezone.now() - timedelta(days=7)
    for row in rows:
        tracked_users.add(row.actor_id)
        if row.created_at >= seven_days_ago:
            active_users_7d.add(row.actor_id)
        parts = str(row.action or "").split(":", 2)
        if len(parts) == 3:
            areas[parts[1]] += 1
            actions[parts[2]] += 1
        category = str((row.metadata or {}).get("category") or "").strip().upper()
        if category:
            categories[category] += 1
        if bool((row.metadata or {}).get("completed")):
            completed += 1
    return {
        "period_days": days,
        "tracked_users": len(tracked_users),
        "active_users_7d": len(active_users_7d),
        "action_count": len(rows),
        "completed_actions": completed,
        "top_areas": [{"area": area, "count": count} for area, count in areas.most_common(10)],
        "top_actions": [{"action": action, "count": count} for action, count in actions.most_common(10)],
        "top_categories": [{"category": category, "count": count} for category, count in categories.most_common(10)],
    }


class SyncUsageTrackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        area = _clean_token(request.data.get("area"), maximum=32)
        action = _clean_token(request.data.get("action"), maximum=64)
        if area not in ALLOWED_AREAS:
            return Response({"area": "Unsupported usage area."}, status=status.HTTP_400_BAD_REQUEST)
        if not action:
            return Response({"action": "Action is required."}, status=status.HTTP_400_BAD_REQUEST)

        metadata = _safe_metadata(request.data.get("metadata"))
        AuditLog.objects.create(
            actor=request.user,
            action=f"{USAGE_PREFIX}:{area}:{action}",
            metadata=metadata,
        )
        return Response({"recorded": True}, status=status.HTTP_201_CREATED)


class SyncUsageSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_usage_summary(request.user))


class SyncGodModeUsageSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False)):
            return Response({"detail": "God Mode access required."}, status=status.HTTP_403_FORBIDDEN)
        return Response(build_platform_usage_summary())
