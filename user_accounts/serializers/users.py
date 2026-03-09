# backend/user_accounts/serializers/users.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user_accounts.models.customer_settings import CustomerSettings

User = get_user_model()


class CustomerSettingsSerializer(serializers.ModelSerializer):
    # Convenience payloads for frontend
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
            # entitlements + profiles
            "entitlements",
            "profiles",
            # timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "entitlements", "profiles"]

    def get_entitlements(self, obj: CustomerSettings) -> dict:
        return obj.entitlements_payload()

    def get_profiles(self, obj: CustomerSettings) -> dict:
        return {
            "finance_profile": obj.finance_profile or {},
            "fitness_profile": obj.fitness_profile or {},
        }


class UserMeSerializer(serializers.ModelSerializer):
    customer_settings = serializers.SerializerMethodField()
    entitlements = serializers.SerializerMethodField()
    profiles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "role",
            "first_name",
            "last_name",
            "is_platform_admin",
            "is_staff",
            "is_superuser",

            # ✅ NEW for paid modules + settings page
            "customer_settings",
            "entitlements",
            "profiles",
        ]
        read_only_fields = fields

    def _get_or_create_settings(self, user: User) -> CustomerSettings:
        """
        Production-safe: guarantees settings exist even for older users created
        before we added the signal/model.
        """
        try:
            cs = getattr(user, "customer_settings", None)
            if cs:
                return cs
        except Exception:
            pass

        cs, _ = CustomerSettings.objects.get_or_create(user=user)
        return cs

    def get_customer_settings(self, obj: User) -> dict:
        cs = self._get_or_create_settings(obj)
        return CustomerSettingsSerializer(cs).data

    def get_entitlements(self, obj: User) -> dict:
        """
        Single source of truth for frontend paywall:
          entitlements.finance_access, entitlements.finance_until
          entitlements.health_access, entitlements.health_until

        ✅ Superusers / platform admins get full access automatically.
        """
        if bool(getattr(obj, "is_superuser", False) or getattr(obj, "is_platform_admin", False)):
            return {
                "finance_access": True,
                "finance_until": None,
                "health_access": True,
                "health_until": None,
            }

        cs = self._get_or_create_settings(obj)
        return cs.entitlements_payload()

    def get_profiles(self, obj: User) -> dict:
        """
        Questionnaire outputs (JSON) for rules-based personalization.
        """
        cs = self._get_or_create_settings(obj)
        return {
            "finance_profile": cs.finance_profile or {},
            "fitness_profile": cs.fitness_profile or {},
        }
