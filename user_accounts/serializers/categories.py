# user_accounts/serializers/categories.py
from __future__ import annotations

from rest_framework import serializers
from user_accounts.models import ServiceCategory


class ServiceCategorySerializer(serializers.ModelSerializer):
    parent_id = serializers.IntegerField(source="parent.id", read_only=True)
    is_leaf = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "name",
            "key",
            "parent",
            "parent_id",
            "is_leaf",
            "is_active",
            "sort_order",
            "created_at",
        ]
        read_only_fields = ["id", "parent_id", "is_leaf", "created_at"]

        extra_kwargs = {
            "parent": {"required": False, "allow_null": True},
        }

    def get_is_leaf(self, obj) -> bool:
        # leaf = no ACTIVE children
        return not obj.children.filter(is_active=True).exists()
