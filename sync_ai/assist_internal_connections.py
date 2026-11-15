"""Read-only connection inventory for the Sync Assist private pilot.

Internal business records require no third-party OAuth. Social URLs are profile
metadata only, never connected API credentials or authorization.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q

from user_accounts.models import Business, BusinessMember, PMProperty
from .assist_pilot_views import _pilot


SOCIAL_FIELDS = (
    ("facebook", "facebook_url"), ("instagram", "instagram_url"),
    ("linkedin", "linkedin_url"), ("google_business", "google_business_url"),
    ("youtube", "youtube_url"), ("tiktok", "tiktok_url"),
)


class SyncAssistInternalConnectionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        user = request.user
        manageable = BusinessMember.objects.filter(
            user=user, is_active=True, role__in=["OWNER", "MANAGER"]
        ).values_list("business_id", flat=True)
        businesses = Business.objects.filter(
            Q(owner=user) | Q(id__in=manageable),
            is_active=True,
            is_demo=False,
        ).distinct().order_by("name", "id")[:100]
        result = []
        for biz in businesses:
            owner = biz.owner_id == user.pk
            pm_count = PMProperty.objects.filter(business_id=biz.pk).count()
            social = [{
                "channel": key,
                "profile_url": getattr(biz, field, "") or "",
                "status": "profile_saved" if getattr(biz, field, "") else "not_configured",
                "api_connected": False,
            } for key, field in SOCIAL_FIELDS]
            result.append({
                "id": biz.pk,
                "name": biz.name,
                "access": "owner" if owner else "manager",
                "scan_eligible": owner,
                "business_email_configured": bool(biz.business_email),
                "properties": pm_count,
                "social": social,
                "whatsapp": {"status": "not_connected", "api_connected": False},
                "operations": {"status": "available_read_only"},
            })
        return Response({
            "pilot": True,
            "internal_businesses": result,
            "counts": {
                "visible": len(result),
                "scan_eligible": sum(1 for item in result if item["scan_eligible"]),
            },
            "external_social_automation_enabled": False,
            "whatsapp_connected": False,
            "notice": "Saved profile links do not grant access to Facebook, Instagram, or WhatsApp. No external actions are enabled.",
        })
