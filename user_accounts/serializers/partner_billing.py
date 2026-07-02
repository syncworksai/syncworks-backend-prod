from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import (
    PartnerInvoice,
    PartnerPayment,
    PartnerPaymentAllocation,
)


class PartnerPaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerPaymentAllocation
        fields = [
            "id",
            "partner_payment",
            "customer_invoice",
            "source_ticket",
            "allocated_amount_cents",
            "lineage_key",
            "platform_fee_already_assessed",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class PartnerPaymentSerializer(serializers.ModelSerializer):
    allocations = PartnerPaymentAllocationSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = PartnerPayment
        fields = [
            "id",
            "invoice",
            "amount_cents",
            "method",
            "status",
            "processor_fee_amount_cents",
            "external_reference",
            "receipt_url",
            "notes",
            "stripe_payment_intent_id",
            "stripe_charge_id",
            "stripe_transfer_id",
            "recorded_by",
            "confirmed_by",
            "recorded_at",
            "confirmed_at",
            "updated_at",
            "allocations",
        ]
        read_only_fields = fields


class PartnerInvoiceSerializer(serializers.ModelSerializer):
    issuing_business_name = serializers.CharField(
        source="issuing_business.name",
        read_only=True,
    )
    paying_business_name = serializers.CharField(
        source="paying_business.name",
        read_only=True,
    )
    source_ticket_id = serializers.IntegerField(
        source="work_ticket.source_ticket_id",
        read_only=True,
    )
    balance_due_cents = serializers.IntegerField(read_only=True)
    payments = PartnerPaymentSerializer(many=True, read_only=True)
    partner_internal_profit_cents = serializers.SerializerMethodField()

    class Meta:
        model = PartnerInvoice
        fields = [
            "id",
            "work_ticket",
            "source_ticket_id",
            "issuing_business",
            "issuing_business_name",
            "paying_business",
            "paying_business_name",
            "invoice_number",
            "title",
            "notes",
            "line_items",
            "subtotal_cents",
            "tax_cents",
            "total_cents",
            "amount_paid_cents",
            "balance_due_cents",
            "status",
            "fee_treatment",
            "fee_lineage_key",
            "platform_fee_rate_bps",
            "platform_fee_amount_cents",
            "processor_fee_amount_cents",
            "partner_internal_profit_cents",
            "due_date",
            "submitted_at",
            "approved_at",
            "paid_at",
            "disputed_at",
            "voided_at",
            "created_by",
            "approved_by",
            "created_at",
            "updated_at",
            "payments",
        ]
        read_only_fields = fields

    def get_partner_internal_profit_cents(self, obj):
        if (
            self.context.get("active_business_id")
            != obj.issuing_business_id
        ):
            return None
        return (
            int(obj.total_cents or 0)
            - int(obj.work_ticket.partner_internal_cost_cents or 0)
            - int(obj.processor_fee_amount_cents or 0)
            - int(obj.platform_fee_amount_cents or 0)
        )
