# backend/user_accounts/serializers/investor_portal.py
from __future__ import annotations

from rest_framework import serializers


class InvestorPropertyRowSerializer(serializers.Serializer):
    property_id = serializers.IntegerField()
    property_name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    city = serializers.CharField(allow_blank=True)
    state = serializers.CharField(allow_blank=True)
    zip = serializers.CharField(allow_blank=True)

    unit_count = serializers.IntegerField()
    occupied_count = serializers.IntegerField()

    # Redacted finance status
    rent_amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    days_past_due = serializers.IntegerField(allow_null=True)
    rent_status = serializers.CharField()  # CURRENT | PAST_DUE | UNKNOWN

    # Maintenance rollups (safe stubs until you wire maintenance)
    open_workorders = serializers.IntegerField()
    recent_workorders_30d = serializers.IntegerField()


class InvestorDashboardSerializer(serializers.Serializer):
    investor_id = serializers.IntegerField()
    investor_name = serializers.CharField()
    businesses = serializers.ListField(child=serializers.IntegerField())
    properties = InvestorPropertyRowSerializer(many=True)
