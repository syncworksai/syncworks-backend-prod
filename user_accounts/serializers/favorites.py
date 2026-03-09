from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import FavoriteBusiness, Business


class BusinessMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "base_zip",
            "service_radius_miles",
            "accepts_marketplace_tickets",
            "business_card_code",
        ]
        read_only_fields = fields


class FavoriteBusinessSerializer(serializers.ModelSerializer):
    business = BusinessMiniSerializer(read_only=True)
    business_id = serializers.PrimaryKeyRelatedField(
        source="business",
        queryset=Business.objects.all(),
        write_only=True,
    )

    class Meta:
        model = FavoriteBusiness
        fields = [
            "id",
            "customer",
            "business",
            "business_id",
            "nickname",
            "last_used_at",
            "created_at",
        ]
        read_only_fields = ["id", "customer", "business", "last_used_at", "created_at"]


class FavoriteBusinessClaimSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    nickname = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")