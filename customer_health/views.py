from __future__ import annotations

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.customer_settings import CustomerSettings

from .models import CustomerHealthProfile
from .serializers import (
    CustomerHealthProfileSerializer,
    RedeemHealthAccessCodeSerializer,
)


def _configured_health_access_code() -> str:
    return str(
        getattr(
            settings,
            "HEALTH_LIFETIME_ACCESS_CODE",
            "SWFIT26",
        )
        or "SWFIT26"
    ).strip().upper()


class CustomerHealthMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request) -> CustomerHealthProfile:
        profile, _created = (
            CustomerHealthProfile.objects.get_or_create(
                user=request.user
            )
        )
        return profile

    def get(self, request):
        profile = self.get_object(request)
        serializer = CustomerHealthProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request):
        profile = self.get_object(request)

        serializer = CustomerHealthProfileSerializer(
            profile,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


class RedeemHealthAccessCodeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = RedeemHealthAccessCodeSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        submitted_code = serializer.validated_data["code"]
        expected_code = _configured_health_access_code()

        if submitted_code != expected_code:
            return Response(
                {
                    "detail": (
                        "Health & Fitness access code is invalid."
                    ),
                    "valid": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer_settings, _created = (
            CustomerSettings.objects.select_for_update()
            .get_or_create(user=request.user)
        )

        customer_settings.health_access = True
        customer_settings.health_until = None
        customer_settings.health_fitness_enabled = True

        customer_settings.save(
            update_fields=[
                "health_access",
                "health_until",
                "health_fitness_enabled",
                "updated_at",
            ]
        )

        CustomerHealthProfile.objects.get_or_create(
            user=request.user
        )

        return Response(
            {
                "detail": (
                    "Health & Fitness has been unlocked "
                    "for this account."
                ),
                "valid": True,
                "code": submitted_code,
                "health_access": True,
                "health_until": None,
                "lifetime_access": True,
            },
            status=status.HTTP_200_OK,
        )

