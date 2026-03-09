# backend/user_accounts/viewsets/me_business_cards.py
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
    -> { business: { id, name, base_zip, service_radius_miles, accepts_marketplace_tickets } }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = (request.query_params.get("code") or "").strip()
        if not code:
            return Response({"detail": "Missing code."}, status=400)

        biz = Business.objects.filter(business_card_code=code).first()
        if not biz:
            return Response({"detail": "Invalid business card code."}, status=404)

        return Response(
            {
                "business": {
                    "id": biz.id,
                    "name": biz.name,
                    "base_zip": biz.base_zip,
                    "service_radius_miles": biz.service_radius_miles,
                    "accepts_marketplace_tickets": biz.accepts_marketplace_tickets,
                }
            },
            status=200,
        )