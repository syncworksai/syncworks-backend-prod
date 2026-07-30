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
        annotated = getattr(obj, "has_active_children", None)
        if annotated is not None:
            return not bool(annotated)

        # Safe fallback for callers that instantiate this serializer with a
        # queryset that does not use ServiceCategoryViewSet._base_qs().
        try:
            return not obj.children.filter(is_active=True).exists()
        except Exception:
            return False

    def get_path(self, obj):
        try:
            chain = []
            current = obj
            guard = 0
            while current and guard < 20:
                chain.insert(0, current.name)
                current = getattr(current, "parent", None)
                guard += 1
            return " → ".join(chain)
        except Exception:
            return obj.name
