# backend/user_accounts/serializers/sales_calendar.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.sales_calendar import SalesCalendarEvent
from user_accounts.models.sales_os import SalesPipelineMember


class SalesCalendarEventSerializer(serializers.ModelSerializer):
    pipeline_id = serializers.IntegerField()
    created_by_id = serializers.IntegerField(read_only=True)

    assigned_member_id = serializers.IntegerField(required=False, allow_null=True)
    prospect_id = serializers.IntegerField(required=False, allow_null=True)

    assigned_member_display = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SalesCalendarEvent
        fields = [
            "id",
            "pipeline_id",
            "created_by_id",
            "assigned_member_id",
            "assigned_member_display",
            "prospect_id",
            "title",
            "description",
            "location",
            "start_at",
            "end_at",
            "is_all_day",
            "is_completed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by_id", "created_at", "updated_at"]

    def get_assigned_member_display(self, obj):
        m = obj.assigned_member
        if not m:
            return None
        u = m.user
        return {
            "member_id": m.id,
            "user_id": u.id,
            "role": m.role,
            "name": (getattr(u, "get_full_name", lambda: "")() or getattr(u, "username", "") or getattr(u, "email", "") or str(u)).strip(),
            "email": getattr(u, "email", "") or "",
        }


class SalesCalendarRangeQuerySerializer(serializers.Serializer):
    pipeline_id = serializers.IntegerField()
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)