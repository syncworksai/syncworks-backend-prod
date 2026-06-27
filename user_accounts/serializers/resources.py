from rest_framework import serializers

from user_accounts.models import (
    BusinessResource,
    ResourceAssignment,
    ResourceMovement,
)


class BusinessResourceSerializer(serializers.ModelSerializer):
    open_assignment_count = serializers.IntegerField(read_only=True, default=0)
    available_capacity = serializers.SerializerMethodField()

    class Meta:
        model = BusinessResource
        fields = [
            "id",
            "business",
            "name",
            "resource_type",
            "status",
            "location",
            "capacity",
            "skills",
            "availability",
            "metadata",
            "is_active",
            "open_assignment_count",
            "available_capacity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "open_assignment_count",
            "available_capacity",
            "created_at",
            "updated_at",
        ]

    def get_available_capacity(self, obj):
        used = getattr(obj, "open_assignment_count", 0) or 0
        return max((obj.capacity or 0) - used, 0)

    def validate_capacity(self, value):
        if value < 1:
            raise serializers.ValidationError("Capacity must be at least 1.")
        return value

    def validate_skills(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("skills must be a JSON list.")
        return value

    def validate_availability(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("availability must be a JSON object.")
        return value

    def validate_metadata(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be a JSON object.")
        return value


class ResourceAssignmentSerializer(serializers.ModelSerializer):
    resource_name = serializers.CharField(source="resource.name", read_only=True)
    resource_type = serializers.CharField(source="resource.resource_type", read_only=True)

    class Meta:
        model = ResourceAssignment
        fields = [
            "id",
            "resource",
            "resource_name",
            "resource_type",
            "ticket",
            "status",
            "starts_at",
            "ends_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "resource_name",
            "resource_type",
            "ticket",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        starts_at = attrs.get("starts_at")
        ends_at = attrs.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be after start time."}
            )
        return attrs


class ResourceMovementSerializer(serializers.ModelSerializer):
    resource_name = serializers.CharField(source="resource.name", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)

    class Meta:
        model = ResourceMovement
        fields = [
            "id",
            "resource",
            "resource_name",
            "asset",
            "asset_name",
            "ticket",
            "from_location",
            "to_location",
            "reason",
            "moved_at",
        ]
        read_only_fields = [
            "id",
            "resource",
            "resource_name",
            "asset_name",
            "ticket",
            "moved_at",
        ]
