from __future__ import annotations

from rest_framework import serializers

from platform_affiliates.models import ReferralAttribution


class ReferralAttributionSerializer(serializers.ModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    affiliate_code = serializers.CharField(source="affiliate.code", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = ReferralAttribution
        fields = [
            "id",
            "business",
            "business_name",
            "affiliate",
            "affiliate_name",
            "affiliate_code",
            "referral_code",
            "attribution_source",
            "locked_at",
            "assigned_by",
            "admin_note",
            "effective_from",
            "retroactive",
            "created_at",
            "updated_at",
        ]