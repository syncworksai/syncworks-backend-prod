from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user_accounts.models.customer_settings import (
    CustomerSettings,
)

User = get_user_model()


class CustomerSettingsSerializer(
    serializers.ModelSerializer
):
    entitlements = serializers.SerializerMethodField()
    profiles = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSettings
        fields = [
            "default_zip",
            "default_address",
            "notify_email",
            "notify_sms",
            "notify_push",
            "preferred_calendar_provider",
            "calendar_sync_enabled",
            "entitlements",
            "profiles",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "created_at",
            "updated_at",
            "entitlements",
            "profiles",
        ]

    def get_entitlements(
        self,
        obj: CustomerSettings,
    ) -> dict:
        return obj.entitlements_payload()

    def get_profiles(
        self,
        obj: CustomerSettings,
    ) -> dict:
        return {
            "finance_profile": (
                obj.finance_profile or {}
            ),
            "fitness_profile": (
                obj.fitness_profile or {}
            ),
        }


class UserMeSerializer(serializers.ModelSerializer):
    customer_settings = (
        serializers.SerializerMethodField()
    )

    entitlements = serializers.SerializerMethodField()
    profiles = serializers.SerializerMethodField()

    affiliate_code = serializers.CharField(
        source="affiliate_referral_code",
        read_only=True,
    )

    referred_by_affiliate_name = (
        serializers.CharField(
            source="referred_by_affiliate.name",
            read_only=True,
            default="",
        )
    )

    class Meta:
        model = User

        fields = [
            "id",
            "email",
            "username",
            "role",
            "first_name",
            "last_name",
            "email_verified",
            "registration_source",
            "affiliate_code",
            "referred_by_affiliate_name",
            "is_platform_admin",
            "is_staff",
            "is_superuser",
            "customer_settings",
            "entitlements",
            "profiles",
        ]

        read_only_fields = fields

    def _get_or_create_settings(
        self,
        user: User,
    ) -> CustomerSettings:
        try:
            settings_obj = getattr(
                user,
                "customer_settings",
                None,
            )

            if settings_obj:
                return settings_obj
        except Exception:
            pass

        settings_obj, _ = (
            CustomerSettings.objects.get_or_create(
                user=user
            )
        )

        return settings_obj

    def get_customer_settings(
        self,
        obj: User,
    ) -> dict:
        settings_obj = (
            self._get_or_create_settings(obj)
        )

        return CustomerSettingsSerializer(
            settings_obj
        ).data

    def get_entitlements(
        self,
        obj: User,
    ) -> dict:
        if bool(
            getattr(obj, "is_superuser", False)
            or getattr(
                obj,
                "is_platform_admin",
                False,
            )
        ):
            return {
                "finance_access": True,
                "finance_until": None,
                "health_access": True,
                "health_until": None,
            }

        settings_obj = (
            self._get_or_create_settings(obj)
        )

        return settings_obj.entitlements_payload()

    def get_profiles(
        self,
        obj: User,
    ) -> dict:
        settings_obj = (
            self._get_or_create_settings(obj)
        )

        return {
            "finance_profile": (
                settings_obj.finance_profile or {}
            ),
            "fitness_profile": (
                settings_obj.fitness_profile or {}
            ),
        }