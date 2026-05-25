from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.models import AffiliatePartner
from platform_affiliates.permissions import IsGodModeAffiliateAdmin
from platform_affiliates.serializers import (
    AffiliatePartnerDetailSerializer,
    AffiliatePartnerListSerializer,
    GodModeAffiliateCreateSerializer,
    GodModeAffiliateOpsDetailSerializer,
    GodModeAffiliateUpdateSerializer,
    GodModeAssignBusinessSerializer,
    ReferralAttributionSerializer,
)
from platform_affiliates.services.attribution_service import assign_business_to_affiliate
from platform_affiliates.services.metrics_service import (
    affiliate_list_metrics_queryset,
    get_godmode_overview_metrics,
)
from user_accounts.models import Business


class GodModeAffiliateOverviewView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def get(self, request):
        return Response(get_godmode_overview_metrics())


class GodModeAffiliateListCreateView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def get(self, request):
        qs = affiliate_list_metrics_queryset()
        return Response({"results": AffiliatePartnerListSerializer(qs, many=True).data})

    def post(self, request):
        serializer = GodModeAffiliateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        affiliate = serializer.save()

        return Response(
            AffiliatePartnerDetailSerializer(affiliate).data,
            status=status.HTTP_201_CREATED,
        )


class GodModeAffiliateDetailView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def get_object(self, pk):
        return AffiliatePartner.objects.get(pk=pk)

    def get(self, request, pk: int):
        affiliate = self.get_object(pk)
        return Response(GodModeAffiliateOpsDetailSerializer(affiliate).data)

    def patch(self, request, pk: int):
        affiliate = self.get_object(pk)
        serializer = GodModeAffiliateUpdateSerializer(
            affiliate,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        affiliate = serializer.save()

        return Response(GodModeAffiliateOpsDetailSerializer(affiliate).data)


class GodModeAssignBusinessView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def post(self, request):
        serializer = GodModeAssignBusinessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        business = Business.objects.get(id=serializer.validated_data["business_id"])
        affiliate = AffiliatePartner.objects.get(id=serializer.validated_data["affiliate_id"])

        attribution = assign_business_to_affiliate(
            business=business,
            affiliate=affiliate,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
            effective_from=serializer.validated_data.get("effective_from") or timezone.localdate(),
            retroactive=serializer.validated_data.get("retroactive", False),
        )

        return Response(
            {
                "message": "Business assigned to affiliate.",
                "attribution": ReferralAttributionSerializer(attribution).data,
            },
            status=status.HTTP_201_CREATED,
        )