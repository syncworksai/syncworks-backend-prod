from __future__ import annotations

from rest_framework import serializers

from platform_affiliates.models import AffiliateCommissionLedger


class AffiliateCommissionLedgerSerializer(serializers.ModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    affiliate_code = serializers.CharField(source="affiliate.code", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = AffiliateCommissionLedger
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "affiliate_code",
            "business",
            "business_name",
            "attribution",
            "revenue_source",
            "gross_revenue_amount",
            "net_syncworks_revenue_amount",
            "commission_rate_bps",
            "commission_amount",
            "status",
            "source_reference",
            "source_date",
            "payout_batch",
            "memo",
            "created_at",
            "updated_at",
        ]