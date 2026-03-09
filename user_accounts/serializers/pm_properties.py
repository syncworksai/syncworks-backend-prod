# backend/user_accounts/serializers/pm_properties.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_property import PMProperty


class PMPropertySerializer(serializers.ModelSerializer):
    # read from queryset annotations
    units_count = serializers.IntegerField(source="units_count_anno", read_only=True)
    section8_units = serializers.IntegerField(source="section8_units_anno", read_only=True)
    occupancy_rate = serializers.SerializerMethodField()

    class Meta:
        model = PMProperty
        fields = [
            "id",
            "business",
            "name",
            "property_type",
            "address",
            "city",
            "state",
            "zip",
            "notes",
            "status",
            "units_count",
            "occupancy_rate",
            "section8_units",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "units_count",
            "occupancy_rate",
            "section8_units",
            "created_at",
            "updated_at",
        ]

    def get_occupancy_rate(self, obj: PMProperty) -> float:
        total = int(getattr(obj, "units_count_anno", 0) or 0)
        if total <= 0:
            return 0.0
        occupied = int(getattr(obj, "occupied_units_anno", 0) or 0)
        return round(occupied / total, 4)
