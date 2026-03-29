from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from user_accounts.models import ServiceCatalogItem


class ServiceCatalogItemSerializer(serializers.ModelSerializer):
    gross_profit_per_unit = serializers.SerializerMethodField()
    gross_margin_pct = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCatalogItem
        fields = [
            "id",
            "business",
            "name",
            "sku",
            "description",
            "item_type",
            "unit_label",
            "default_quantity",
            "unit_price",
            "unit_cost",
            "gross_profit_per_unit",
            "gross_margin_pct",
            "is_active",
            "is_featured",
            "requires_quote",
            "allow_direct_checkout",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "gross_profit_per_unit",
            "gross_margin_pct",
            "created_at",
            "updated_at",
        ]

    def get_gross_profit_per_unit(self, obj) -> str:
        try:
            return str(obj.gross_profit_per_unit)
        except Exception:
            return "0.00"

    def get_gross_margin_pct(self, obj) -> str:
        try:
            return str(obj.gross_margin_pct)
        except Exception:
            return "0.00"

    def validate_name(self, v):
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("Name is required.")
        return v

    def validate_sku(self, v):
        return (v or "").strip()

    def validate_unit_label(self, v):
        return (v or "").strip()

    def validate_description(self, v):
        return (v or "").strip()

    def validate_default_quantity(self, v):
        try:
            val = Decimal(str(v))
        except Exception:
            raise serializers.ValidationError("default_quantity must be a valid number.")
        if val <= 0:
            raise serializers.ValidationError("default_quantity must be greater than 0.")
        return val

    def validate_unit_price(self, v):
        try:
            val = Decimal(str(v))
        except Exception:
            raise serializers.ValidationError("unit_price must be a valid number.")
        if val < 0:
            raise serializers.ValidationError("unit_price cannot be negative.")
        return val

    def validate_unit_cost(self, v):
        try:
            val = Decimal(str(v))
        except Exception:
            raise serializers.ValidationError("unit_cost must be a valid number.")
        if val < 0:
            raise serializers.ValidationError("unit_cost cannot be negative.")
        return val