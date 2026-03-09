# backend/user_accounts/serializers/customer_settings.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.customer_settings import CustomerSettings


class CustomerSettingsSerializer(serializers.ModelSerializer):
    entitlements = serializers.SerializerMethodField()
    profiles = serializers.SerializerMethodField()
    profile_photo_url = serializers.SerializerMethodField()
    customer_profile = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSettings
        fields = [
            "id",
            "user",

            # customer identity
            "prefix",
            "suffix",
            "phone",
            "preferred_contact_method",
            "profile_photo",
            "profile_photo_url",

            # defaults / preferences
            "default_zip",
            "default_address",
            "notify_email",
            "notify_sms",
            "notify_push",
            "preferred_calendar_provider",
            "calendar_sync_enabled",

            # payment metadata
            "stripe_customer_id",
            "stripe_payment_method_id",
            "stripe_payment_method_brand",
            "stripe_payment_method_last4",
            "stripe_payment_method_exp_month",
            "stripe_payment_method_exp_year",

            # entitlements raw
            "finance_access",
            "finance_until",
            "health_access",
            "health_until",

            # questionnaire JSON
            "finance_profile",
            "fitness_profile",

            # legacy
            "health_fitness_enabled",
            "finance_tools_enabled",

            # computed payloads
            "entitlements",
            "profiles",
            "customer_profile",
            "payment",

            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "created_at",
            "updated_at",
            "entitlements",
            "profiles",
            "profile_photo_url",
            "customer_profile",
            "payment",

            # payment IDs should not be edited directly from generic PATCH
            "stripe_customer_id",
            "stripe_payment_method_id",
            "stripe_payment_method_brand",
            "stripe_payment_method_last4",
            "stripe_payment_method_exp_month",
            "stripe_payment_method_exp_year",
        ]

    def get_entitlements(self, obj: CustomerSettings) -> dict:
        return obj.entitlements_payload()

    def get_profiles(self, obj: CustomerSettings) -> dict:
        return {
            "finance_profile": obj.finance_profile or {},
            "fitness_profile": obj.fitness_profile or {},
        }

    def get_profile_photo_url(self, obj: CustomerSettings) -> str | None:
        try:
            if obj.profile_photo and hasattr(obj.profile_photo, "url"):
                return obj.profile_photo.url
        except Exception:
            return None
        return None

    def get_customer_profile(self, obj: CustomerSettings) -> dict:
        u = getattr(obj, "user", None)
        return {
            "email": getattr(u, "email", None),
            "first_name": getattr(u, "first_name", "") or "",
            "last_name": getattr(u, "last_name", "") or "",
            "prefix": obj.prefix or "NONE",
            "suffix": obj.suffix or "",
            "phone": obj.phone or "",
            "preferred_contact_method": obj.preferred_contact_method or "EMAIL",
        }

    def get_payment(self, obj: CustomerSettings) -> dict:
        return obj.payment_payload()


class CustomerSettingsUpdateSerializer(serializers.ModelSerializer):
    """
    Write-safe serializer for preferences + customer profile.
    (Stripe payment fields are managed via dedicated endpoints later.)
    """

    class Meta:
        model = CustomerSettings
        fields = [
            # customer identity
            "prefix",
            "suffix",
            "phone",
            "preferred_contact_method",
            "profile_photo",

            # defaults / preferences
            "default_zip",
            "default_address",
            "notify_email",
            "notify_sms",
            "notify_push",
            "preferred_calendar_provider",
            "calendar_sync_enabled",

            # questionnaires
            "finance_profile",
            "fitness_profile",
        ]

    def validate_default_zip(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 10:
            raise serializers.ValidationError("ZIP too long.")
        return value

    def validate_phone(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 32:
            raise serializers.ValidationError("Phone too long.")
        return value

    def validate_preferred_calendar_provider(self, value: str) -> str:
        value = (value or "").strip().upper()
        allowed = {c[0] for c in CustomerSettings.CalendarProvider.choices}
        if value not in allowed:
            raise serializers.ValidationError(f"Invalid calendar provider. Allowed: {sorted(list(allowed))}")
        return value

    def validate_prefix(self, value: str) -> str:
        value = (value or "NONE").strip().upper()
        allowed = {c[0] for c in CustomerSettings.Prefix.choices}
        if value not in allowed:
            raise serializers.ValidationError("Invalid prefix.")
        return value

    def validate_preferred_contact_method(self, value: str) -> str:
        value = (value or "EMAIL").strip().upper()
        allowed = {c[0] for c in CustomerSettings.PreferredContact.choices}
        if value not in allowed:
            raise serializers.ValidationError("Invalid contact method.")
        return value
