from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_unit import PMUnit


class PMUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMUnit
        fields = [
            "id",
            "business",
            "property",
            "label",
            "beds",
            "baths",
            "status",
            "section8_eligible",
            "section8_active",
            "market_rent",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]
