"""Founder-pilot persisted employee display/role preferences.

This API configures the four existing portrait slots. Assignment roles are
validated against the workday role registry and do not expand tool privileges.
No secrets, outbound integrations or user-provided code is accepted.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .assist_workday_views import ROLES

ACTION = "sync_assist.team.config_updated"
SLOTS = {
    "executive-female": {"name": "Victoria", "role": "CHIEF_OF_STAFF"},
    "executive-male": {"name": "James", "role": "SALES_MANAGER"},
    "future-female": {"name": "Elizabeth", "role": "MARKETING_MANAGER"},
    "future-male": {"name": "William", "role": "RESEARCH_ANALYST"},
}
MAX_NAME_LENGTH = 32
# These roles presently have bounded, auditable internal task handlers.
EXECUTABLE_ROLES = {"CHIEF_OF_STAFF", "RESEARCH_ANALYST", "SALES_MANAGER"}


def team_snapshot(user):
    items = {key: {"id": key, **default} for key, default in SLOTS.items()}
    latest = AuditLog.objects.filter(actor=user, action=ACTION).order_by("-id").first()
    if latest:
        overrides = (latest.metadata or {}).get("employees", {})
        if isinstance(overrides, dict):
            for key, item in overrides.items():
                if key in items and isinstance(item, dict):
                    name, role = item.get("name"), item.get("role")
                    if isinstance(name, str) and 1 <= len(name.strip()) <= MAX_NAME_LENGTH:
                        items[key]["name"] = name.strip()
                    if role in ROLES:
                        items[key]["role"] = role
    return {
        "employees": [
            {**item, "execution_status": "internal_pilot" if item["role"] in EXECUTABLE_ROLES else "not_implemented"}
            for item in items.values()
        ],
        "allowed_roles": sorted(ROLES),
        "notice": "Roles are assignment labels, not permission grants. Only marked internal-pilot roles can execute existing audited work. External actions remain disabled.",
    }


class SyncAssistTeamView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response(team_snapshot(request.user))

    def put(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        submitted = request.data.get("employees")
        if not isinstance(submitted, list) or len(submitted) != len(SLOTS):
            return Response({"detail": "Provide exactly the four existing employee slots."}, status=400)
        overrides = {}
        used_roles = set()
        for row in submitted:
            if not isinstance(row, dict) or set(row.keys()) != {"id", "name", "role"}:
                return Response({"detail": "Each employee requires id, name and role only."}, status=400)
            key, name, role = row["id"], row["name"], row["role"]
            if not isinstance(key, str) or key not in SLOTS or key in overrides:
                return Response({"detail": "Unknown or duplicate employee."}, status=400)
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= MAX_NAME_LENGTH:
                return Response({"detail": "Employee names must be 1–32 characters."}, status=400)
            if not isinstance(role, str) or role not in ROLES or role in used_roles:
                return Response({"detail": "Assign each employee a different supported role."}, status=400)
            used_roles.add(role)
            overrides[key] = {"name": name.strip(), "role": role}
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            AuditLog.objects.create(actor=request.user, action=ACTION, metadata={"employees": overrides})
        return Response(team_snapshot(request.user))
