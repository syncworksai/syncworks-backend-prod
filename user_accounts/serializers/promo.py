from __future__ import annotations

from rest_framework import serializers
from user_accounts.models import PromoCode, PromoRedemption


class PromoCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromoCode
        fields = [
            "id",
            "code",
            "is_active",
            "billing_exempt",
            "expires_at",
            "max_redemptions",
            "redemption_count",
            "notes",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "redemption_count", "created_by", "created_at"]


class PromoRedemptionSerializer(serializers.ModelSerializer):
    promo_code = serializers.CharField(source="promo.code", read_only=True)

    class Meta:
        model = PromoRedemption
        fields = ["id", "promo", "promo_code", "user", "business", "redeemed_at"]
        read_only_fields = ["id", "redeemed_at", "promo_code"]
