from __future__ import annotations

import re

from rest_framework import serializers

from user_accounts.models import AssetIdentifier, TicketAssetLink, TrackableAsset


def normalize_identifier(value: str, identifier_type: str = "") -> str:
    raw = str(value or "").strip().upper()
    kind = str(identifier_type or "").strip().upper()

    if kind in {
        AssetIdentifier.IdentifierType.VIN,
        AssetIdentifier.IdentifierType.BARCODE,
        AssetIdentifier.IdentifierType.UPC,
        AssetIdentifier.IdentifierType.SKU,
        AssetIdentifier.IdentifierType.SERIAL_NUMBER,
        AssetIdentifier.IdentifierType.KEY_TAG,
        AssetIdentifier.IdentifierType.PURCHASE_ORDER,
        AssetIdentifier.IdentifierType.SYNCWORKS_QR,
        AssetIdentifier.IdentifierType.LICENSE_PLATE,
    }:
        return re.sub(r"[^A-Z0-9]", "", raw)

    return re.sub(r"\s+", " ", raw)


class AssetIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetIdentifier
        fields = [
            "id",
            "identifier_type",
            "value",
            "normalized_value",
            "source",
            "is_primary",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "normalized_value", "created_at"]


class TrackableAssetSerializer(serializers.ModelSerializer):
    identifiers = AssetIdentifierSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    syncworks_scan_value = serializers.SerializerMethodField()

    class Meta:
        model = TrackableAsset
        fields = [
            "id",
            "business",
            "customer",
            "customer_name",
            "asset_type",
            "name",
            "description",
            "status",
            "make",
            "model",
            "year",
            "location",
            "metadata",
            "public_token",
            "syncworks_scan_value",
            "is_active",
            "identifiers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "customer_name",
            "public_token",
            "syncworks_scan_value",
            "identifiers",
            "created_at",
            "updated_at",
        ]

    def get_customer_name(self, obj):
        user = getattr(obj, "customer", None)
        if not user:
            return ""
        try:
            full = (user.get_full_name() or "").strip()
        except Exception:
            full = ""
        return full or getattr(user, "email", "") or getattr(user, "username", "")

    def get_syncworks_scan_value(self, obj):
        return f"SW-ASSET-{obj.public_token}"

    def validate_metadata(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be a JSON object.")
        return value


class TicketAssetLinkSerializer(serializers.ModelSerializer):
    asset_detail = TrackableAssetSerializer(source="asset", read_only=True)

    class Meta:
        model = TicketAssetLink
        fields = ["id", "ticket", "asset", "asset_detail", "role", "notes", "created_at"]
        read_only_fields = ["id", "ticket", "asset_detail", "created_at"]
