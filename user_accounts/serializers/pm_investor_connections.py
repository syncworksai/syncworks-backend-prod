# backend/user_accounts/serializers/pm_investor_connections.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_investor_connection import PMInvestorConnection


class PMInvestorConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMInvestorConnection
        fields = [
            "id",
            "investor",
            "business_id",
            "status",
            "connect_code",
            "created_at",
            "accepted_at",
            "revoked_at",
        ]
        read_only_fields = ["id", "connect_code", "created_at", "accepted_at", "revoked_at"]


class PMInvestorConnectByCodeSerializer(serializers.Serializer):
    """
    Investor enters a connect_code to accept the connection to a PM company.
    """
    connect_code = serializers.CharField(max_length=64)
