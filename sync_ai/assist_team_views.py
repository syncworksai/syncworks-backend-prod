"""Founder-pilot persisted employee display/role preferences.

This API configures stable role slots, including planned employees. Assignment roles are
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

ACTION = "sync_assist.team.config_updated"
SLOTS = {
    "executive-female": {"name": "Victoria", "role": "CHIEF_OF_STAFF"},
    "executive-male": {"name": "James", "role": "SALES_MANAGER"},
    "future-female": {"name": "Elizabeth", "role": "MARKETING_MANAGER"},
    "future-male": {"name": "William", "role": "RESEARCH_ANALYST"},
    "executive-assistant": {"name": "Executive Assistant", "role": "EXECUTIVE_ASSISTANT"},
    "business-manager": {"name": "Business Operations", "role": "BUSINESS_MANAGER"},
    "finance-manager": {"name": "Finance Analyst", "role": "FINANCE_MANAGER"},
    "property-manager": {"name": "Property Assistant", "role": "PROPERTY_MANAGER"},
    "customer-service": {"name": "Customer Service", "role": "CUSTOMER_SERVICE"},
    "personal-trainer": {"name": "Fitness Coach", "role": "PERSONAL_TRAINER"},
}
MAX_NAME_LENGTH = 32
PHOTO_CHOICES = {
    "/jarvis-avatars/victoria.jpeg", "/jarvis-avatars/james.jpeg",
    "/jarvis-avatars/elizabeth.jpeg", "/jarvis-avatars/william.jpeg",
    "/lady10.png",
}
DEFAULT_PHOTOS = {
    "executive-female": "/lady10.png",
    "executive-male": "/jarvis-avatars/james.jpeg",
    "future-female": "/jarvis-avatars/elizabeth.jpeg",
    "future-male": "/jarvis-avatars/william.jpeg",
    "executive-assistant": "/jarvis-avatars/victoria.jpeg",
    "business-manager": "/jarvis-avatars/james.jpeg",
    "finance-manager": "/jarvis-avatars/william.jpeg",
    "property-manager": "/jarvis-avatars/elizabeth.jpeg",
    "customer-service": "/jarvis-avatars/victoria.jpeg",
    "personal-trainer": "/jarvis-avatars/james.jpeg",
}

# These roles presently have bounded, auditable internal task handlers.
EXECUTABLE_ROLES = {"CHIEF_OF_STAFF", "RESEARCH_ANALYST", "SALES_MANAGER", "MARKETING_MANAGER", "EXECUTIVE_ASSISTANT"}


def team_snapshot(user):
    items = {key: {"id": key, **default, "photo": DEFAULT_PHOTOS[key]} for key, default in SLOTS.items()}
    latest = AuditLog.objects.filter(actor=user, action=ACTION).order_by("-id").first()
    if latest:
        overrides = (latest.metadata or {}).get("employees", {})
        if isinstance(overrides, dict):
            for key, item in overrides.items():
                if key in items and isinstance(item, dict):
                    name, photo = item.get("name"), item.get("photo")
                    if isinstance(name, str) and 1 <= len(name.strip()) <= MAX_NAME_LENGTH:
                        items[key]["name"] = name.strip()
                    if photo in PHOTO_CHOICES:
                        items[key]["photo"] = photo
    return {
        "employees": [
            {**item, "execution_status": "internal_pilot" if item["role"] in EXECUTABLE_ROLES else "not_implemented"}
            for item in items.values()
        ],
        "allowed_roles": [entry["role"] for entry in SLOTS.values()],
        "photo_choices": sorted(PHOTO_CHOICES),
        "pilot_entitlement": "FREE_TEST_ACCOUNT",
        "notice": "Employee roles are fixed and do not grant permission to use tools. Only marked internal-pilot roles can execute existing audited work. External actions remain disabled.",
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
            return Response({"detail": "Provide exactly the ten fixed employee role slots."}, status=400)
        overrides = {}
        for row in submitted:
            if not isinstance(row, dict) or set(row.keys()) not in ({"id", "name", "role"}, {"id", "name", "role", "photo"}):
                return Response({"detail": "Each employee requires id, name, fixed role and optional approved photo."}, status=400)
            key, name, role = row["id"], row["name"], row["role"]
            photo = row.get("photo", DEFAULT_PHOTOS.get(key))
            if not isinstance(key, str) or key not in SLOTS or key in overrides:
                return Response({"detail": "Unknown or duplicate employee."}, status=400)
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= MAX_NAME_LENGTH:
                return Response({"detail": "Employee names must be 1–32 characters."}, status=400)
            if role != SLOTS[key]["role"]:
                return Response({"detail": "Employee roles are fixed. Customize only the name and portrait."}, status=400)
            if photo not in PHOTO_CHOICES:
                return Response({"detail": "Choose one of the approved employee portraits."}, status=400)
            overrides[key] = {"name": name.strip(), "photo": photo}
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            AuditLog.objects.create(actor=request.user, action=ACTION, metadata={"employees": overrides})
        return Response(team_snapshot(request.user))
