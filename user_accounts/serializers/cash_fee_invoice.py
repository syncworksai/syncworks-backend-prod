# backend/user_accounts/serializers/cash_fee_invoice.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import CashFeeInvoice


class CashFeeInvoiceSerializer(serializers.ModelSerializer):
    business_name = serializers.SerializerMethodField()

    class Meta:
        model = CashFeeInvoice
        fields = [
            "id",
            "business",
            "business_name",
            "status",
            "currency",
            "amount_cents",
            "period_start",
            "period_end",
            "due_date",
            "paid_at",
            "memo",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "business_name",
            "created_by",
            "created_at",
            "updated_at",
            "paid_at",
        ]

    def get_business_name(self, obj) -> str:
        try:
            return obj.business.name or ""
        except Exception:
            return ""