from rest_framework import serializers

from .models import EdgeExchangeConnection, EdgePaperTrade, EdgeSignal, EdgeStrategy


class EdgeExchangeConnectionSerializer(serializers.ModelSerializer):
    connected = serializers.SerializerMethodField()

    class Meta:
        model = EdgeExchangeConnection
        fields = [
            "id", "exchange", "environment", "can_read", "can_trade", "is_active",
            "last_verified_at", "connected", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_connected(self, obj):
        return bool(obj.api_key_id and obj.encrypted_private_key and obj.is_active)


class EdgeStrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = EdgeStrategy
        fields = "__all__"
        read_only_fields = ["id", "user", "created_at", "updated_at"]


class EdgeSignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EdgeSignal
        fields = "__all__"
        read_only_fields = ["id", "user", "observed_at"]


class EdgePaperTradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EdgePaperTrade
        fields = "__all__"
        read_only_fields = ["id", "user", "created_at", "closed_at", "pnl_cents"]
