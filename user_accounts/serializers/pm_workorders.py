from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import PMWorkOrder


class PMWorkOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMWorkOrder
        fields = [
            "id",
            "business",
            "property",
            "unit",
            "tenant",
            "title",
            "description",
            "status",
            "priority",
            "due_date",
            "assigned_to_email",
            "assignment_mode",
            "assigned_member",
            "marketplace_ticket",
            "marketplace_requested_at",
            "created_by",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "created_by",
            "created_at",
            "updated_at",
            "marketplace_ticket",
            "marketplace_requested_at",
        ]


class PMWorkOrderAssignSerializer(serializers.Serializer):
    """
    POST /api/v1/pm/workorders/{id}/assign/
    Body:
      { "mode": "TECH", "assigned_member_id": 123 }
      OR
      { "mode": "MARKETPLACE" }
      OR
      { "mode": "CLEAR" }
    """

    mode = serializers.ChoiceField(choices=["TECH", "MARKETPLACE", "CLEAR"])
    assigned_member_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        mode = attrs.get("mode")
        mid = attrs.get("assigned_member_id")

        if mode == "TECH" and not mid:
            raise serializers.ValidationError({"assigned_member_id": "Required when mode=TECH"})
        return attrs
