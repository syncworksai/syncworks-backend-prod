# user_accounts/serializers/kpis.py
from __future__ import annotations

from rest_framework import serializers
from user_accounts.models import PlatformDailyKpi, BusinessDailyKpi, MarketplaceCellDailyKpi


class PlatformDailyKpiSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformDailyKpi
        fields = "__all__"


class BusinessDailyKpiSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessDailyKpi
        fields = "__all__"


class MarketplaceCellDailyKpiSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketplaceCellDailyKpi
        fields = "__all__"
