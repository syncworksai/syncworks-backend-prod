from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import (
    PartnerWorkChangeOrder,
    PartnerWorkEstimate,
)


class PartnerWorkEstimateSerializer(serializers.ModelSerializer):
    partner_business_name = serializers.CharField(
        source="work_ticket.partner_business.name",
        read_only=True,
    )
    hiring_business_name = serializers.CharField(
        source="work_ticket.hiring_business.name",
        read_only=True,
    )
    hiring_business_notes = serializers.SerializerMethodField()

    class Meta:
        model = PartnerWorkEstimate
        fields = [
            "id",
            "work_ticket",
            "revision",
            "status",
            "title",
            "scope",
            "line_items",
            "subtotal_cents",
            "tax_cents",
            "total_cents",
            "estimated_days",
            "valid_until",
            "partner_notes",
            "hiring_business_notes",
            "partner_business_name",
            "hiring_business_name",
            "created_by",
            "reviewed_by",
            "created_at",
            "updated_at",
            "submitted_at",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_hiring_business_notes(self, obj):
        if (
            self.context.get("active_business_id")
            == obj.work_ticket.hiring_business_id
        ):
            return obj.hiring_business_notes
        return None


class PartnerWorkChangeOrderSerializer(serializers.ModelSerializer):
    partner_business_name = serializers.CharField(
        source="work_ticket.partner_business.name",
        read_only=True,
    )
    hiring_business_name = serializers.CharField(
        source="work_ticket.hiring_business.name",
        read_only=True,
    )
    customer_amount_delta_cents = serializers.SerializerMethodField()
    hiring_business_notes = serializers.SerializerMethodField()

    class Meta:
        model = PartnerWorkChangeOrder
        fields = [
            "id",
            "work_ticket",
            "sequence",
            "status",
            "title",
            "reason",
            "scope_delta",
            "line_items",
            "partner_amount_delta_cents",
            "customer_amount_delta_cents",
            "schedule_days_delta",
            "partner_notes",
            "hiring_business_notes",
            "partner_business_name",
            "hiring_business_name",
            "created_by",
            "reviewed_by",
            "created_at",
            "updated_at",
            "submitted_at",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_customer_amount_delta_cents(self, obj):
        if (
            self.context.get("active_business_id")
            == obj.work_ticket.hiring_business_id
        ):
            return obj.customer_amount_delta_cents
        return None

    def get_hiring_business_notes(self, obj):
        if (
            self.context.get("active_business_id")
            == obj.work_ticket.hiring_business_id
        ):
            return obj.hiring_business_notes
        return None
