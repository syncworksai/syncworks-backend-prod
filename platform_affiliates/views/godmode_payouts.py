from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.models import AffiliatePayoutBatch, AffiliatePartner
from platform_affiliates.permissions import IsGodModeAffiliateAdmin
from platform_affiliates.serializers import (
    AffiliatePayoutBatchSerializer,
    CreateAffiliatePayoutBatchSerializer,
    MarkAffiliatePayoutPaidSerializer,
)
from platform_affiliates.services.payout_service import (
    create_monthly_payout_batch,
    mark_payout_batch_paid,
)


class GodModePayoutBatchListCreateView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def get(self, request):
        qs = AffiliatePayoutBatch.objects.select_related("affiliate").order_by(
            "-period_end",
            "-created_at",
        )
        return Response({"results": AffiliatePayoutBatchSerializer(qs, many=True).data})

    def post(self, request):
        serializer = CreateAffiliatePayoutBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        affiliate = get_object_or_404(
            AffiliatePartner,
            id=serializer.validated_data["affiliate_id"],
        )

        batch = create_monthly_payout_batch(
            affiliate=affiliate,
            period_start=serializer.validated_data["period_start"],
            period_end=serializer.validated_data["period_end"],
            notes=serializer.validated_data.get("notes", ""),
        )

        return Response(
            AffiliatePayoutBatchSerializer(batch).data,
            status=status.HTTP_201_CREATED,
        )


class GodModePayoutBatchMarkPaidView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def post(self, request, pk: int):
        batch = get_object_or_404(AffiliatePayoutBatch, id=pk)

        serializer = MarkAffiliatePayoutPaidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        batch = mark_payout_batch_paid(
            batch=batch,
            external_reference=serializer.validated_data.get("external_reference", ""),
            notes=serializer.validated_data.get("notes", ""),
        )

        return Response(AffiliatePayoutBatchSerializer(batch).data)