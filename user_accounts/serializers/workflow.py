from rest_framework import serializers

from user_accounts.models import TicketDependency, TicketRequirement


class TicketRequirementSerializer(serializers.ModelSerializer):
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    resource_name = serializers.CharField(source="resource.name", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = TicketRequirement
        fields = [
            "id",
            "ticket",
            "requirement_type",
            "title",
            "description",
            "status",
            "severity",
            "blocks_progress",
            "due_at",
            "is_overdue",
            "satisfied_at",
            "satisfied_by",
            "asset",
            "asset_name",
            "resource",
            "resource_name",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "is_overdue",
            "satisfied_at",
            "satisfied_by",
            "asset_name",
            "resource_name",
            "created_at",
            "updated_at",
        ]

    def get_is_overdue(self, obj):
        from django.utils import timezone

        return bool(
            obj.status == TicketRequirement.Status.OPEN
            and obj.due_at
            and obj.due_at < timezone.now()
        )

    def validate_metadata(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be a JSON object.")
        return value


class TicketDependencySerializer(serializers.ModelSerializer):
    depends_on_status = serializers.CharField(
        source="depends_on_ticket.status",
        read_only=True,
    )
    is_satisfied = serializers.SerializerMethodField()

    class Meta:
        model = TicketDependency
        fields = [
            "id",
            "ticket",
            "depends_on_ticket",
            "depends_on_status",
            "description",
            "is_blocking",
            "is_satisfied",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "depends_on_status",
            "is_satisfied",
            "created_at",
        ]

    def get_is_satisfied(self, obj):
        return obj.depends_on_ticket.status in {
            "COMPLETED",
            "INVOICED",
            "PAID",
            "CLOSED",
        }
