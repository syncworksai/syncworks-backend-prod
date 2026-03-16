from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business


class MeBusinessCardResolveAPIView(APIView):
    """
    Resolve a business by business_card_code (SW-...).
    Used by customer to add a favorite via paste/scan.

    GET /api/v1/me/business-cards/resolve/?code=SW-xxxx
    """
    permission_classes = [IsAuthenticated]

    def _logo_url(self, request, biz: Business):
        try:
            if not biz.logo:
                return None
            return request.build_absolute_uri(biz.logo.url)
        except Exception:
            return None

    def _display_location(self, biz: Business) -> str:
        city = (getattr(biz, "city", "") or "").strip()
        state = (getattr(biz, "state", "") or "").strip()
        if city and state:
            return f"{city}, {state}"
        return city or state or ""

    def get(self, request):
        code = (request.query_params.get("code") or "").strip()
        if not code:
            return Response({"detail": "Missing code."}, status=400)

        biz = Business.objects.filter(business_card_code=code, is_active=True).first()
        if not biz:
            return Response({"detail": "Invalid business card code."}, status=404)

        return Response(
            {
                "business": {
                    "id": biz.id,
                    "name": biz.name,
                    "logo_url": self._logo_url(request, biz),
                    "headline": getattr(biz, "headline", "") or "",
                    "services_text": getattr(biz, "services_text", "") or "",
                    "business_email": getattr(biz, "business_email", "") or "",
                    "phone": getattr(biz, "phone", "") or "",
                    "address": getattr(biz, "address", "") or "",
                    "city": getattr(biz, "city", "") or "",
                    "state": getattr(biz, "state", "") or "",
                    "display_location": self._display_location(biz),
                    "website": getattr(biz, "website", "") or "",
                    "base_zip": getattr(biz, "base_zip", "") or "",
                    "service_radius_miles": getattr(biz, "service_radius_miles", 25),
                    "accepts_marketplace_tickets": bool(getattr(biz, "accepts_marketplace_tickets", False)),
                    "business_card_code": getattr(biz, "business_card_code", "") or "",
                    "is_licensed": bool(getattr(biz, "is_licensed", False)),
                    "is_insured": bool(getattr(biz, "is_insured", False)),
                    "is_bonded": bool(getattr(biz, "is_bonded", False)),
                    "background_checked": bool(getattr(biz, "background_checked", False)),
                    "emergency_service": bool(getattr(biz, "emergency_service", False)),
                }
            },
            status=200,
        )