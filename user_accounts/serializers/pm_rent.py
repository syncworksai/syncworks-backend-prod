# backend/user_accounts/serializers/pm_rent.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import (
    PMBillingSettings,
    PMRentCharge,
    PMRentPayment,
    PMRentPaymentAllocation,
)


class PMBillingSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for PMBillingSettings.

    IMPORTANT:
    - Model fields do NOT include cc_email.
    - We only expose actual model fields.
    """

    class Meta:
        model = PMBillingSettings
        fields = [
            "id",
            "business_id",

            # Rent / billing cadence defaults
            "rent_due_day",
            "grace_days",

            # Late fee rule
            "late_fee_enabled",
            "late_fee_type",
            "late_fee_flat_amount",
            "late_fee_percent",

            # Automation toggles
            "auto_email_enabled",
            "email_send_on_due",
            "email_send_on_past_due",
            "email_send_on_late_fee",

            # Reminder schedule
            "remind_days_before_due",
            "remind_days_after_due",

            # Optional from name/email
            "from_name",
            "from_email",

            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business_id", "created_at", "updated_at"]


class PMRentPaymentAllocationSerializer(serializers.ModelSerializer):
    # Helpful read-only denorm fields
    charge_id = serializers.IntegerField(source="charge.id", read_only=True)
    charge_type = serializers.CharField(source="charge.charge_type", read_only=True)
    due_date = serializers.DateField(source="charge.due_date", read_only=True)

    class Meta:
        model = PMRentPaymentAllocation
        fields = [
            "id",
            "payment",
            "charge",
            "charge_id",
            "amount",
            "charge_type",
            "due_date",
        ]
        # ✅ allocations are created by server logic, not client
        read_only_fields = [
            "id",
            "payment",
            "charge",
            "charge_id",
            "charge_type",
            "due_date",
        ]


class PMRentChargeSerializer(serializers.ModelSerializer):
    total_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    # Helpful relation ids
    property_id = serializers.IntegerField(source="property.id", read_only=True)
    unit_id = serializers.IntegerField(source="unit.id", read_only=True)
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = PMRentCharge
        fields = [
            "id",
            "business_id",

            "property",
            "unit",
            "tenant",

            "property_id",
            "unit_id",
            "tenant_id",

            "due_date",
            "charge_type",
            "amount",
            "total_paid",
            "balance",
            "status",
            "description",
            "notes",

            "related_charge",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business_id",
            "total_paid",
            "balance",
            "created_at",
            "updated_at",
        ]


class PMRentPaymentSerializer(serializers.ModelSerializer):
    allocations = PMRentPaymentAllocationSerializer(many=True, read_only=True)

    charge_id = serializers.IntegerField(source="charge.id", read_only=True)
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = PMRentPayment
        fields = [
            "id",
            "business_id",
            "tenant",
            "tenant_id",
            "charge",
            "charge_id",
            "amount",
            "method",
            "reference",
            "paid_at",
            "created_at",
            "allocations",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "charge_id",
            "tenant_id",
            "allocations",
        ]
