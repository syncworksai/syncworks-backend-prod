# user_accounts/serializers/platform_console.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user_accounts.models import Business, PlatformBillingProfile

User = get_user_model()


class PlatformUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    is_platform_admin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "role",
            "is_platform_admin",
        ]

    def get_role(self, obj):
        return getattr(obj, "role", None)

    def get_is_platform_admin(self, obj):
        return bool(getattr(obj, "is_platform_admin", False))


class PlatformBillingProfileMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformBillingProfile
        fields = [
            "stripe_setup_complete",
            "is_locked",
            "lock_reason",
            "locked_at",
            "next_due_date",
            "grace_until",
            "subscription_status",
            "subscription_cancel_at_period_end",
            "subscription_current_period_end",
        ]


class PlatformBusinessSerializer(serializers.ModelSerializer):
    billing_profile = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "owner_id",
            "created_at",
            "billing_profile",
        ]

    def get_billing_profile(self, obj):
        try:
            prof = getattr(obj, "billing_profile", None)
            if not prof:
                prof = PlatformBillingProfile.objects.filter(business=obj).first()
            return PlatformBillingProfileMiniSerializer(prof).data if prof else None
        except Exception:
            return None
