from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.models import AffiliatePartner, ReferralClick
from platform_affiliates.services.attribution_service import get_client_ip
from platform_affiliates.services.code_generator import normalize_affiliate_code


class TrackAffiliateClickView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        code = normalize_affiliate_code(request.data.get("code", ""))
        landing_path = str(request.data.get("landing_path", "") or "")

        affiliate = AffiliatePartner.objects.filter(code=code).first()

        ReferralClick.objects.create(
            affiliate=affiliate,
            code=code,
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            landing_path=landing_path,
        )

        return Response({"ok": True}, status=status.HTTP_201_CREATED)


class ResolveAffiliateCodeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        code = normalize_affiliate_code(request.data.get("code", ""))
        affiliate = AffiliatePartner.objects.filter(code=code, status="ACTIVE").first()

        if not affiliate:
            return Response(
                {
                    "valid": False,
                    "code": code,
                    "affiliate_name": "",
                }
            )

        return Response(
            {
                "valid": True,
                "code": affiliate.code,
                "affiliate_name": affiliate.name,
            }
        )