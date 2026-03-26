from __future__ import annotations

from rest_framework import serializers
from user_accounts.models import ServiceCategory


class ServiceCategorySerializer(serializers.ModelSerializer):
    is_leaf = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField(source="parent.id", read_only=True)
    path = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "name",
            "key",
            "parent_id",
            "sort_order",
            "is_active",
            "is_leaf",
            "path",
        ]

    def get_is_leaf(self, obj):
        try:
            return not obj.children.filter(is_active=True).exists()
        except Exception:
            return False

    def get_path(self, obj):
        try:
            chain = []
            cur = obj
            guard = 0
            while cur and guard < 20:
                chain.insert(0, cur.name)
                cur = getattr(cur, "parent", None)
                guard += 1
            return " → ".join(chain)
        except Exception:
            return obj.name