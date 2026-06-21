from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user_accounts.models.user import (
    EmailVerificationChallenge,
)

User = get_user_model()


class StartEmailVerificationSerializer(
    serializers.Serializer
):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(
        choices=(
            EmailVerificationChallenge
            .PURPOSE_CHOICES
        ),
        default=(
            EmailVerificationChallenge
            .PURPOSE_REGISTER
        ),
    )

    def validate_email(self, value):
        return str(value or "").strip().lower()

    def validate(self, attrs):
        email = attrs["email"]
        purpose = attrs["purpose"]

        if (
            purpose
            == EmailVerificationChallenge
            .PURPOSE_REGISTER
            and User.objects
            .filter(email__iexact=email)
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "email": (
                        "An account already exists "
                        "with this email."
                    )
                }
            )

        return attrs


class VerifyEmailCodeSerializer(
    serializers.Serializer
):
    challenge_id = serializers.UUIDField()
    code = serializers.RegexField(
        regex=r"^\d{6}$",
        error_messages={
            "invalid": (
                "Enter the six-digit verification code."
            )
        },
    )


class ResendEmailCodeSerializer(
    serializers.Serializer
):
    challenge_id = serializers.UUIDField()


class ResolveSignupCodeSerializer(
    serializers.Serializer
):
    affiliate_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
    )

    promo_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
    )