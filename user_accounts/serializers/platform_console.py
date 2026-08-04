# user_accounts/serializers/platform_console.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user_accounts.models import Business, PlatformBillingProfile
from user_accounts.models.user_classification import PlatformUserClassification

User = get_user_model()


class PlatformUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    is_platform_admin = serializers.SerializerMethodField()
    classification = serializers.SerializerMethodField()
    classification_note = serializers.SerializerMethodField()
    classified_at = serializers.SerializerMethodField()
    suggested_classification = serializers.SerializerMethodField()
    businesses_count = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "display_name",
            "is_active", "is_staff", "is_superuser", "date_joined",
            "last_login", "role", "is_platform_admin", "businesses_count",
            "classification", "classification_note", "classified_at",
            "suggested_classification",
        ]

    def _classification(self, obj):
        try:
            return obj.platform_classification
        except PlatformUserClassification.DoesNotExist:
            return None

    def get_role(self, obj):
        return getattr(obj, "role", None)

    def get_is_platform_admin(self, obj):
        return bool(getattr(obj, "is_platform_admin", False) or obj.is_superuser)

    def get_display_name(self, obj):
        full = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return full or getattr(obj, "username", "") or obj.email

    def get_businesses_count(self, obj):
        try:
            owned = obj.businesses.count()
        except Exception:
            owned = Business.objects.filter(owner=obj).count()
        return owned

    def get_classification(self, obj):
        item = self._classification(obj)
        return item.kind if item else PlatformUserClassification.Kind.UNCLASSIFIED

    def get_classification_note(self, obj):
        item = self._classification(obj)
        return item.note if item else ""

    def get_classified_at(self, obj):
        item = self._classification(obj)
        return item.classified_at if item else None

    def get_suggested_classification(self, obj):
        text = " ".join([
            str(getattr(obj, "username", "") or ""),
            str(obj.email or ""),
            str(obj.first_name or ""),
            str(obj.last_name or ""),
        ]).lower()
        return "TEST_ACCOUNT" if "test" in text else None


class PlatformBillingProfileMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformBillingProfile
        fields = [
            "stripe_setup_complete", "is_locked", "lock_reason", "locked_at",
            "next_due_date", "grace_until", "subscription_status",
            "subscription_cancel_at_period_end", "subscription_current_period_end",
        ]


class PlatformBusinessSerializer(serializers.ModelSerializer):
    billing_profile = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = ["id", "name", "owner_id", "created_at", "billing_profile"]

    def get_billing_profile(self, obj):
        try:
            prof = getattr(obj, "billing_profile", None)
            if not prof:
                prof = PlatformBillingProfile.objects.filter(business=obj).first()
            return PlatformBillingProfileMiniSerializer(prof).data if prof else None
        except Exception:
            return None
