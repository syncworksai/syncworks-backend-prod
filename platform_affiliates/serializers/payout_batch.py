from __future__ import annotations

from rest_framework import serializers

from platform_affiliates.models import AffiliatePayoutBatch


class AffiliatePayoutBatchSerializer(serializers.ModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    affiliate_code = serializers.CharField(source="affiliate.code", read_only=True)

    class Meta:
        model = AffiliatePayoutBatch
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "affiliate_code",
            "period_start",
            "period_end",
            "total_amount",
            "status",
            "paid_at",
            "external_reference",
            "notes",
            "created_at",
            "updated_at",
        ]


class CreateAffiliatePayoutBatchSerializer(serializers.Serializer):
    affiliate_id = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)


class MarkAffiliatePayoutPaidSerializer(serializers.Serializer):
    external_reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)