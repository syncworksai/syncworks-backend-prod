# user_accounts/serializers/platform_console.py
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework import serializers

from user_accounts.models import Business, PlatformBillingProfile
from user_accounts.models.billing import Invoice
from user_accounts.models.business_customers import BusinessCustomer
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
    intelligence = serializers.SerializerMethodField()
    billing_summary = serializers.SerializerMethodField()
    verified_value = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "display_name",
            "is_active", "is_staff", "is_superuser", "date_joined",
            "last_login", "role", "is_platform_admin", "businesses_count",
            "classification", "classification_note", "classified_at",
            "suggested_classification", "intelligence", "billing_summary",
            "verified_value",
        ]

    def _classification(self, obj):
        try:
            return obj.platform_classification
        except PlatformUserClassification.DoesNotExist:
            return None

    def _owned_businesses(self, obj):
        try:
            return obj.businesses.all()
        except Exception:
            return Business.objects.filter(owner=obj)

    def get_role(self, obj):
        return getattr(obj, "role", None)

    def get_is_platform_admin(self, obj):
        # Informational only. God Mode authorization is controlled separately by
        # user_accounts.services.god_mode.is_god_mode().
        return bool(getattr(obj, "is_platform_admin", False) or obj.is_superuser)

    def get_display_name(self, obj):
        full = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return full or getattr(obj, "username", "") or obj.email

    def get_businesses_count(self, obj):
        return self._owned_businesses(obj).count()

    def get_classification(self, obj):
        item = self._classification(obj)
        return item.kind if item else PlatformUserClassification.Kind.UNCLASSIFIED

    def get_classification_note(self, obj):
        item = self._classification(obj)
        return item.note if item else ""

    def get_classified_at(self, obj):
        item = self._classification(obj)
        return item.classified_at if item else None

    def get_intelligence(self, obj):
        item = self._classification(obj)
        raw = dict(getattr(item, "intelligence", None) or {})
        roles = list(raw.get("roles") or [])
        detected_roles = []
        account_role = str(getattr(obj, "role", "") or "").strip().upper()
        if account_role:
            detected_roles.append(account_role)
        if self._owned_businesses(obj).exists():
            detected_roles.append("BUSINESS_OWNER")

        return {
            "roles": roles,
            "detected_roles": sorted(set(detected_roles)),
            "modules": list(raw.get("modules") or []),
            "subscriptions": list(raw.get("subscriptions") or []),
            "acquisition_source": str(raw.get("acquisition_source") or "UNKNOWN"),
            "acquisition_detail": str(raw.get("acquisition_detail") or ""),
            "customers_brought": max(0, int(raw.get("customers_brought") or 0)),
            "customers_supplied_by_syncworks": max(0, int(raw.get("customers_supplied_by_syncworks") or 0)),
            "attributed_revenue_cents": max(0, int(raw.get("attributed_revenue_cents") or 0)),
            "paid_cents": max(0, int(raw.get("paid_cents") or 0)),
            "payable_cents": max(0, int(raw.get("payable_cents") or 0)),
        }

    def get_verified_value(self, obj):
        businesses = self._owned_businesses(obj)
        customers = BusinessCustomer.objects.filter(business__in=businesses, exclude_from_kpis=False)
        supplied = customers.filter(record_source=BusinessCustomer.RecordSource.SYNCWORKS).count()
        brought = customers.exclude(record_source=BusinessCustomer.RecordSource.SYNCWORKS).count()
        collected = Invoice.objects.filter(
            ticket__assigned_business__in=businesses,
            platform_fee_collected=True,
        ).aggregate(total=Sum("platform_fee_amount"))["total"] or Decimal("0.00")
        return {
            "customers_brought": brought,
            "customers_supplied_by_syncworks": supplied,
            "platform_revenue_cents": max(0, int(collected * 100)),
            "customer_source": "business_customer_record_source",
            "revenue_source": "collected_invoice_platform_fees",
        }

    def get_billing_summary(self, obj):
        businesses = self._owned_businesses(obj)
        profiles = PlatformBillingProfile.objects.filter(business__in=businesses)
        statuses = sorted({str(value or "UNKNOWN") for value in profiles.values_list("subscription_status", flat=True)})
        return {
            "businesses": businesses.count(),
            "billing_profiles": profiles.count(),
            "locked_businesses": profiles.filter(is_locked=True).count(),
            "payment_method_ready": profiles.filter(stripe_setup_complete=True).count(),
            "subscription_statuses": statuses,
        }

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
