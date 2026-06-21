from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.models import AffiliatePartner
from platform_affiliates.services.code_generator import (
    normalize_affiliate_code,
)
from user_accounts.models.promo import PromoCode
from user_accounts.models.user import (
    EmailVerificationChallenge,
)
from user_accounts.serializers.auth import (
    REGISTRATION_PROOF_SALT,
    RegisterSerializer,
)
from user_accounts.serializers.email_verification import (
    ResendEmailCodeSerializer,
    ResolveSignupCodeSerializer,
    StartEmailVerificationSerializer,
    VerifyEmailCodeSerializer,
)
from user_accounts.serializers.users import (
    UserMeSerializer,
)
from user_accounts.services.email_verification import (
    create_challenge,
    get_client_ip,
    resend_challenge,
)

User = get_user_model()


def _proof_max_age() -> int:
    return int(
        getattr(
            settings,
            "AUTH_REGISTRATION_PROOF_MAX_AGE_SECONDS",
            1800,
        )
    )


class StartEmailVerificationAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StartEmailVerificationSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        challenge = create_challenge(
            email=serializer.validated_data["email"],
            purpose=serializer.validated_data[
                "purpose"
            ],
            ip_address=get_client_ip(request),
            user_agent=request.META.get(
                "HTTP_USER_AGENT",
                "",
            ),
        )

        return Response(
            {
                "detail": "Verification code sent.",
                "challenge_id": str(
                    challenge.public_id
                ),
                "expires_in": int(
                    (
                        challenge.expires_at
                        - timezone.now()
                    ).total_seconds()
                ),
                "resend_after": int(
                    getattr(
                        settings,
                        (
                            "AUTH_EMAIL_RESEND_"
                            "COOLDOWN_SECONDS"
                        ),
                        60,
                    )
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailCodeAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = VerifyEmailCodeSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        challenge = (
            EmailVerificationChallenge.objects
            .select_for_update()
            .filter(
                public_id=(
                    serializer.validated_data[
                        "challenge_id"
                    ]
                )
            )
            .first()
        )

        if not challenge:
            return Response(
                {
                    "detail": (
                        "Verification request "
                        "was not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if challenge.is_consumed:
            return Response(
                {
                    "detail": (
                        "Verification request "
                        "is no longer active."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if challenge.is_expired:
            return Response(
                {
                    "detail": (
                        "Verification code expired."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if challenge.attempt_count >= int(
            getattr(
                settings,
                "AUTH_EMAIL_MAX_VERIFY_ATTEMPTS",
                6,
            )
        ):
            return Response(
                {
                    "detail": (
                        "Too many incorrect attempts. "
                        "Request a new code."
                    )
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        raw_code = serializer.validated_data[
            "code"
        ]

        if not challenge.check_code(raw_code):
            challenge.attempt_count += 1
            challenge.save(
                update_fields=["attempt_count"]
            )

            return Response(
                {
                    "detail": (
                        "Verification code is incorrect."
                    ),
                    "attempts_remaining": max(
                        0,
                        int(
                            getattr(
                                settings,
                                (
                                    "AUTH_EMAIL_MAX_"
                                    "VERIFY_ATTEMPTS"
                                ),
                                6,
                            )
                        )
                        - challenge.attempt_count,
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        challenge.verified_at = timezone.now()
        challenge.save(
            update_fields=["verified_at"]
        )

        registration_proof = signing.dumps(
            {
                "email": challenge.email,
                "purpose": challenge.purpose,
                "challenge_id": str(
                    challenge.public_id
                ),
            },
            salt=REGISTRATION_PROOF_SALT,
            compress=True,
        )

        return Response(
            {
                "verified": True,
                "email": challenge.email,
                "registration_proof": (
                    registration_proof
                ),
                "proof_expires_in": _proof_max_age(),
            },
            status=status.HTTP_200_OK,
        )


class ResendEmailCodeAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendEmailCodeSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        challenge = (
            EmailVerificationChallenge.objects
            .filter(
                public_id=(
                    serializer.validated_data[
                        "challenge_id"
                    ]
                )
            )
            .first()
        )

        if not challenge:
            return Response(
                {
                    "detail": (
                        "Verification request "
                        "was not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        challenge = resend_challenge(
            challenge=challenge
        )

        return Response(
            {
                "detail": (
                    "A new verification code was sent."
                ),
                "challenge_id": str(
                    challenge.public_id
                ),
                "expires_in": int(
                    (
                        challenge.expires_at
                        - timezone.now()
                    ).total_seconds()
                ),
            },
            status=status.HTTP_200_OK,
        )


class ResolveSignupCodesAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResolveSignupCodeSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        affiliate_code = normalize_affiliate_code(
            serializer.validated_data.get(
                "affiliate_code",
                "",
            )
        )

        promo_code = str(
            serializer.validated_data.get(
                "promo_code",
                "",
            )
            or ""
        ).strip().upper()

        affiliate_payload = {
            "provided": bool(affiliate_code),
            "valid": False,
            "code": affiliate_code,
            "name": "",
        }

        promo_payload = {
            "provided": bool(promo_code),
            "valid": False,
            "code": promo_code,
            "description": "",
        }

        if affiliate_code:
            affiliate = (
                AffiliatePartner.objects
                .filter(
                    code=affiliate_code,
                    status="ACTIVE",
                )
                .first()
            )

            if affiliate:
                affiliate_payload.update(
                    {
                        "valid": True,
                        "code": affiliate.code,
                        "name": affiliate.name,
                    }
                )

        if promo_code:
            promo = (
                PromoCode.objects
                .filter(code__iexact=promo_code)
                .first()
            )

            if promo and promo.is_valid_now():
                promo_payload.update(
                    {
                        "valid": True,
                        "code": promo.code,
                        "description": str(
                            getattr(
                                promo,
                                "description",
                                "",
                            )
                            or ""
                        ),
                    }
                )

        return Response(
            {
                "affiliate": affiliate_payload,
                "promo": promo_payload,
            },
            status=status.HTTP_200_OK,
        )


class VerifiedRegisterAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(
            raise_exception=True
        )

        result = serializer.save()

        return Response(
            {
                "token": result["token"],
                "user": UserMeSerializer(
                    result["user"]
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )