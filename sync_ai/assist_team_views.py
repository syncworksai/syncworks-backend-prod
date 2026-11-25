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
    "executive-female": {"name": "Sydney", "role": "CHIEF_OF_STAFF"},
    "executive-male": {"name": "Scarlett", "role": "SALES_MANAGER"},
    "future-female": {"name": "Naomi", "role": "MARKETING_MANAGER"},
    "future-male": {"name": "Sophia", "role": "RESEARCH_ANALYST"},
    "executive-assistant": {"name": "Executive Assistant", "role": "EXECUTIVE_ASSISTANT"},
    "business-manager": {"name": "Business Operations", "role": "BUSINESS_MANAGER"},
    "finance-manager": {"name": "Olivia", "role": "FINANCE_MANAGER"},
    "property-manager": {"name": "Sarah", "role": "PROPERTY_MANAGER"},
    "customer-service": {"name": "Rebecca", "role": "CUSTOMER_SERVICE"},
    "personal-trainer": {"name": "Fitness Coach", "role": "PERSONAL_TRAINER"},
}
MAX_NAME_LENGTH = 32
PHOTO_CHOICES = {
    "/jarvis-avatars/newvictoria.png", "/jarvis-avatars/newsophia.png",
    "/jarvis-avatars/naomi.png", "/jarvis-avatars/newscarlett.png",
    "/jarvis-avatars/customersupport1.png", "/jarvis-avatars/yasmine.png",
    "/jarvis-avatars/christy2.png", "/jarvis-avatars/kylee.png",
    "", # Intentional placeholder until the approved portrait is uploaded.
    "/jarvis-avatars/victoria.jpeg", "/jarvis-avatars/james.jpeg",
    "/jarvis-avatars/elizabeth.jpeg", "/jarvis-avatars/william.jpeg",
    "/lady10.png",
    "/jarvis-avatars/Victoria.png",
    "/jarvis-avatars/Charlotte.png",
    "/jarvis-avatars/Elizabeth.png",
    "/jarvis-avatars/Scarlett.png",
    "/jarvis-avatars/Sophia.png",
    "/jarvis-avatars/Sarah.png",
}
DEFAULT_PHOTOS = {
    "executive-female": "/jarvis-avatars/newvictoria.png",
    "executive-male": "/jarvis-avatars/newscarlett.png",
    "future-female": "/jarvis-avatars/naomi.png",
    "future-male": "/jarvis-avatars/newsophia.png",
    "executive-assistant": "/jarvis-avatars/victoria.jpeg",
    "business-manager": "/jarvis-avatars/james.jpeg",
    "finance-manager": "/jarvis-avatars/Charlotte.png",
    "property-manager": "/jarvis-avatars/Sarah.png",
    "customer-service": "/jarvis-avatars/customersupport1.png",
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
                        # Legacy 4-avatar roster used James and William. Migrate
                        # only those exact defaults, preserving personal renames.
                        old_defaults = {"executive-male": "James", "future-male": "William", "finance-manager": "Finance Analyst"}
                        items[key]["name"] = SLOTS[key]["name"] if name.strip() == old_defaults.get(key) else name.strip()
                    if photo in PHOTO_CHOICES:
                        old_photos = {"executive-male": "/jarvis-avatars/james.jpeg", "future-male": "/jarvis-avatars/william.jpeg", "finance-manager": "/jarvis-avatars/william.jpeg"}
                        items[key]["photo"] = DEFAULT_PHOTOS[key] if photo == old_photos.get(key) or (photo == "" and key in {"executive-male","future-male","finance-manager"}) else photo
    # Explicit founder identity revision: stable slot IDs and role permissions
    # remain intact; legacy names and portraits are migrated on read.
    identity_revision = {"executive-female":{"old_name":"Victoria","old_photo":"/jarvis-avatars/Victoria.png"},"future-female":{"old_name":"Elizabeth","old_photo":"/jarvis-avatars/Elizabeth.png"},"finance-manager":{"old_name":"Charlotte","old_photo":"/jarvis-avatars/Charlotte.png"},"customer-service":{"old_name":"Customer Service","old_photo":"/jarvis-avatars/victoria.jpeg"},"executive-male":{"old_name":"Scarlett","old_photo":"/jarvis-avatars/Scarlett.png"},"future-male":{"old_name":"Sophia","old_photo":"/jarvis-avatars/Sophia.png"}}
    for key, previous in identity_revision.items():
        if items[key]["name"] == previous["old_name"]:
            items[key]["name"] = SLOTS[key]["name"]
        if items[key]["photo"] == previous["old_photo"]:
            items[key]["photo"] = DEFAULT_PHOTOS[key]
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
