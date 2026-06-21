from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from platform_affiliates.models import AffiliatePartner
from platform_affiliates.services.code_generator import normalize_affiliate_code
from user_accounts.models import CustomerProfile
from user_accounts.models.customer_settings import CustomerSettings
from user_accounts.models.promo import PromoCode
from user_accounts.models.user_billing import UserBillingProfile

User = get_user_model()

REGISTRATION_PROOF_SALT = "syncworks.registration.email-proof.v1"


def _normalized_email(value: str) -> str:
    return str(value or "").strip().lower()


def _verification_bypass_emails() -> set[str]:
    raw = getattr(settings, "AUTH_VERIFICATION_BYPASS_EMAILS", [])

    if isinstance(raw, str):
        values = raw.split(",")
    else:
        values = list(raw or [])

    return {
        _normalized_email(value)
        for value in values
        if _normalized_email(value)
    }


def _registration_proof_max_age() -> int:
    return int(
        getattr(
            settings,
            "AUTH_REGISTRATION_PROOF_MAX_AGE_SECONDS",
            1800,
        )
    )


def _validate_registration_proof(
    *,
    proof: str,
    email: str,
) -> dict:
    try:
        payload = signing.loads(
            proof,
            salt=REGISTRATION_PROOF_SALT,
            max_age=_registration_proof_max_age(),
        )
    except signing.SignatureExpired as exc:
        raise serializers.ValidationError(
            {
                "registration_proof": (
                    "Email verification expired. Request a new code."
                )
            }
        ) from exc
    except signing.BadSignature as exc:
        raise serializers.ValidationError(
            {
                "registration_proof": (
                    "Email verification could not be confirmed."
                )
            }
        ) from exc

    proof_email = _normalized_email(payload.get("email"))
    purpose = str(payload.get("purpose") or "").upper()

    if proof_email != email:
        raise serializers.ValidationError(
            {
                "registration_proof": (
                    "Verification does not match this email."
                )
            }
        )

    if purpose != "REGISTER":
        raise serializers.ValidationError(
            {
                "registration_proof": (
                    "Verification is not valid for registration."
                )
            }
        )

    challenge_id = str(payload.get("challenge_id") or "").strip()

    if not challenge_id:
        raise serializers.ValidationError(
            {
                "registration_proof": (
                    "Verification challenge is missing."
                )
            }
        )

    return payload


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    confirm_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    registration_proof = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )

    affiliate_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=32,
    )

    promo_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=64,
    )

    registration_source = serializers.ChoiceField(
        choices=User.REGISTRATION_SOURCE_CHOICES,
        required=False,
        default=User.REGISTRATION_SOURCE_WEB,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "password",
            "confirm_password",
            "first_name",
            "last_name",
            "registration_proof",
            "affiliate_code",
            "promo_code",
            "registration_source",
        )

    def validate_email(self, value):
        email = _normalized_email(value)

        if not email:
            raise serializers.ValidationError(
                "Email is required."
            )

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account already exists with this email."
            )

        return email

    def validate_username(self, value):
        username = str(value or "").strip()

        if not username:
            raise serializers.ValidationError(
                "Username is required."
            )

        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError(
                "This username is already in use."
            )

        return username

    def validate(self, attrs):
        email = _normalized_email(attrs.get("email"))
        password = attrs.get("password") or ""
        confirm_password = attrs.get("confirm_password") or ""
        proof = str(attrs.get("registration_proof") or "").strip()

        if password != confirm_password:
            raise serializers.ValidationError(
                {
                    "confirm_password": (
                        "Passwords do not match."
                    )
                }
            )

        bypassed = email in _verification_bypass_emails()

        if not bypassed:
            if not proof:
                raise serializers.ValidationError(
                    {
                        "registration_proof": (
                            "Verify your email before creating an account."
                        )
                    }
                )

            attrs["_verification_payload"] = (
                _validate_registration_proof(
                    proof=proof,
                    email=email,
                )
            )

        affiliate_code = normalize_affiliate_code(
            attrs.get("affiliate_code", "")
        )

        affiliate = None

        if affiliate_code:
            affiliate = (
                AffiliatePartner.objects
                .filter(
                    code=affiliate_code,
                    status="ACTIVE",
                )
                .first()
            )

            if not affiliate:
                raise serializers.ValidationError(
                    {
                        "affiliate_code": (
                            "Affiliate code is invalid or inactive."
                        )
                    }
                )

        promo_code = str(
            attrs.get("promo_code") or ""
        ).strip().upper()

        promo = None

        if promo_code:
            promo = (
                PromoCode.objects
                .filter(code__iexact=promo_code)
                .first()
            )

            if not promo or not promo.is_valid_now():
                raise serializers.ValidationError(
                    {
                        "promo_code": (
                            "Promo code is invalid, inactive, or expired."
                        )
                    }
                )

        attrs["email"] = email
        attrs["affiliate_code"] = affiliate_code
        attrs["promo_code"] = promo_code
        attrs["_affiliate"] = affiliate
        attrs["_promo"] = promo
        attrs["_verification_bypassed"] = bypassed

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.pop("confirm_password", None)
        validated_data.pop("registration_proof", None)

        affiliate_code = validated_data.pop(
            "affiliate_code",
            "",
        )

        promo_code = validated_data.pop(
            "promo_code",
            "",
        )

        affiliate = validated_data.pop(
            "_affiliate",
            None,
        )

        promo = validated_data.pop(
            "_promo",
            None,
        )

        verification_payload = validated_data.pop(
            "_verification_payload",
            None,
        )

        verification_bypassed = validated_data.pop(
            "_verification_bypassed",
            False,
        )

        user = User(
            **validated_data,
        )

        user.role = User.ROLE_CUSTOMER
        user.email = _normalized_email(user.email)

        user.email_verified = True
        user.email_verified_at = timezone.now()

        if verification_bypassed:
            user.is_test_account = True

        if affiliate:
            user.referred_by_affiliate = affiliate
            user.affiliate_referral_code = affiliate_code
            user.affiliate_attributed_at = timezone.now()

        if promo:
            user.registration_promo_code = promo_code

        user.set_password(password)
        user.save()

        CustomerProfile.objects.get_or_create(user=user)
        CustomerSettings.objects.get_or_create(user=user)

        billing_profile, _ = (
            UserBillingProfile.objects.get_or_create(
                user=user
            )
        )

        if promo:
            billing_exempt = bool(
                getattr(
                    promo,
                    "billing_exempt",
                    False,
                )
            )

            subscriptions_waived = bool(
                getattr(
                    promo,
                    "waive_subscriptions",
                    False,
                )
            )

            billing_profile.grant_beta_access(
                code=promo_code,
                billing_exempt=billing_exempt,
                subscriptions_waived=subscriptions_waived,
            )

            billing_profile.save(
                update_fields=[
                    "beta_access_granted",
                    "beta_access_granted_at",
                    "beta_access_code",
                    "beta_billing_exempt",
                    "beta_subscriptions_waived",
                ]
            )

        if verification_payload:
            from user_accounts.models.user import (
                EmailVerificationChallenge,
            )

            challenge_id = verification_payload.get(
                "challenge_id"
            )

            challenge = (
                EmailVerificationChallenge.objects
                .select_for_update()
                .filter(
                    public_id=challenge_id,
                    email__iexact=user.email,
                    purpose=(
                        EmailVerificationChallenge
                        .PURPOSE_REGISTER
                    ),
                    verified_at__isnull=False,
                    consumed_at__isnull=True,
                )
                .first()
            )

            if not challenge:
                raise serializers.ValidationError(
                    {
                        "registration_proof": (
                            "Verification has already been used "
                            "or is no longer valid."
                        )
                    }
                )

            challenge.consumed_at = timezone.now()
            challenge.save(
                update_fields=["consumed_at"]
            )

        token, _ = Token.objects.get_or_create(
            user=user
        )

        return {
            "user": user,
            "token": token.key,
        }


class TokenLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
    )

    def validate(self, attrs):
        identifier = str(
            attrs.get("identifier") or ""
        ).strip()

        password = attrs.get("password") or ""

        if not identifier or not password:
            raise serializers.ValidationError(
                "Missing credentials."
            )

        user = authenticate(
            username=identifier,
            password=password,
        )

        if user is None:
            matched_user = (
                User.objects
                .filter(email__iexact=identifier)
                .first()
            )

            if matched_user:
                user = authenticate(
                    username=matched_user.username,
                    password=password,
                )

        if user is None:
            raise serializers.ValidationError(
                "Invalid credentials."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "This account is unavailable."
            )

        token, _ = Token.objects.get_or_create(
            user=user
        )

        return {
            "token": token.key,
            "user_id": user.id,
            "email_verified": bool(
                user.email_verified
            ),
        }