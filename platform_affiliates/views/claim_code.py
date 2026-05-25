from __future__ import annotations

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.choices import AttributionSource
from platform_affiliates.serializers import (
    ClaimAffiliateCodeSerializer,
    ReferralAttributionSerializer,
)
from platform_affiliates.services.attribution_service import assign_business_to_affiliate


class ClaimAffiliateCodeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ClaimAffiliateCodeSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        attribution = assign_business_to_affiliate(
            business=serializer.validated_data["business"],
            affiliate=serializer.validated_data["affiliate"],
            actor=request.user,
            source=AttributionSource.MANUAL_CODE,
            reason="Affiliate code claimed by business user.",
            retroactive=False,
        )

        return Response(
            {
                "message": "Affiliate code claimed successfully.",
                "attribution": ReferralAttributionSerializer(attribution).data,
            },
            status=status.HTTP_201_CREATED,
        )