"""Pilot growth campaign and internal operations read-only briefing.

No outbound contact, social posting, mailbox read or payment actions.
Offers here are drafting text only: no price/checkout entitlements change.
"""
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot

CAMPAIGN = "sync_assist.growth.campaign_settings"
DEFAULT = {
    "name": "SyncWorks founding businesses",
    "offer": "Try SyncWorks free through our current signup trial. Ask about our limited founding-business pilot.",
    "call_to_action": "Would you be interested in a quick demo and an invitation?",
    "enabled": False,
}


def _latest(user):
    event = AuditLog.objects.filter(actor=user, action=CAMPAIGN).order_by("-id").first()
    return dict(DEFAULT, **{key: event.metadata.get(key, DEFAULT[key]) for key in DEFAULT}) if event else dict(DEFAULT)


class SyncAssistGrowthCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response({
            "campaign": _latest(request.user),
            "sending_enabled": False,
            "offer_entitlements_changed": False,
            "note": "Draft settings only. Verify trial length, pricing and eligibility in checkout before advertising an extended free offer.",
        })

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        config = {}
        limits = {"name": 100, "offer": 700, "call_to_action": 220}
        for key, limit in limits.items():
            value = request.data.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                return Response({"detail": f"{key} must contain 1–{limit} characters."}, status=400)
            config[key] = value.strip()
        # Only editable campaign content. Enabling delivery is not supported here.
        config["enabled"] = False
        AuditLog.objects.create(actor=request.user, action=CAMPAIGN, metadata=config)
        return Response({"campaign": config, "sending_enabled": False, "offer_entitlements_changed": False})


class SyncAssistOperationsBriefView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        # Use the same owner-only query as the private pilot discovery scanner.
        from .assist_discovery import _candidates
        rows, counts = _candidates(request.user)
        previews = [
            {"kind": item["kind"], "title": item["title"], "description": item["description"]}
            for item in rows[:15]
        ]
        return Response({
            "business_work": {
                "counts": counts,
                "items": previews,
                "checked": True,
                "read_only": True,
            },
            "email": {
                "provider": "outlook",
                "connected": False,
                "read_enabled": False,
                "draft_enabled": False,
                "send_enabled": False,
            },
            "worker": {"scheduled": False, "verified": False},
            "note": "This is an on-demand snapshot of owner-linked SyncWorks work. It does not read external email or run autonomously.",
        })
