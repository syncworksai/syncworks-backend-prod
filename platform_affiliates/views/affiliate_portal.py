from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.models import AffiliateCommissionLedger, AffiliatePartner, ReferralAttribution
from platform_affiliates.permissions import IsCustomerAffiliateApplicant
from platform_affiliates.serializers import (
    AffiliateApplicationSerializer,
    AffiliateCommissionLedgerSerializer,
    AffiliatePartnerDetailSerializer,
    ReferralAttributionSerializer,
)
from platform_affiliates.services.attribution_service import get_client_ip
from platform_affiliates.services.metrics_service import get_affiliate_dashboard_metrics


class AffiliateMeView(APIView):
    permission_classes = [IsCustomerAffiliateApplicant]

    def get(self, request):
        affiliate = AffiliatePartner.objects.filter(user=request.user).first()

        if not affiliate:
            return Response(
                {
                    "has_affiliate_profile": False,
                    "message": "No affiliate application found for this account.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "has_affiliate_profile": True,
                "affiliate": AffiliatePartnerDetailSerializer(affiliate).data,
                "metrics": get_affiliate_dashboard_metrics(affiliate),
            }
        )

    def post(self, request):
        serializer = AffiliateApplicationSerializer(
            data=request.data,
            context={
                "request": request,
                "ip_address": get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            },
        )
        serializer.is_valid(raise_exception=True)
        affiliate = serializer.save()

        return Response(
            {
                "message": "Affiliate application submitted.",
                "affiliate": AffiliatePartnerDetailSerializer(affiliate).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AffiliateMeBusinessesView(APIView):
    permission_classes = [IsCustomerAffiliateApplicant]

    def get(self, request):
        affiliate = AffiliatePartner.objects.filter(user=request.user).first()
        if not affiliate:
            return Response({"results": []})

        qs = ReferralAttribution.objects.select_related("business", "affiliate").filter(affiliate=affiliate)
        return Response({"results": ReferralAttributionSerializer(qs, many=True).data})


class AffiliateMeCommissionsView(APIView):
    permission_classes = [IsCustomerAffiliateApplicant]

    def get(self, request):
        affiliate = AffiliatePartner.objects.filter(user=request.user).first()
        if not affiliate:
            return Response({"results": []})

        qs = AffiliateCommissionLedger.objects.select_related("affiliate", "business", "attribution").filter(
            affiliate=affiliate
        )
        return Response({"results": AffiliateCommissionLedgerSerializer(qs, many=True).data})