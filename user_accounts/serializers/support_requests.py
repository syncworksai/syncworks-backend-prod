# backend/user_accounts/serializers/support_requests.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.support_requests import SupportRequest


class SupportRequestSerializer(serializers.ModelSerializer):
    requester_email = serializers.SerializerMethodField()
    handled_by_email = serializers.SerializerMethodField()

    class Meta:
        model = SupportRequest
        fields = [
            "id",
            "kind",
            "status",
            "role",
            "business_id",
            "title",
            "body",
            "created_at",
            "updated_at",
            "requester",
            "requester_email",
            "handled_by",
            "handled_by_email",
            "handled_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "requester",
            "requester_email",
            "handled_by",
            "handled_by_email",
            "handled_at",
        ]

    def get_requester_email(self, obj):
        u = getattr(obj, "requester", None)
        return getattr(u, "email", "") if u else ""

    def get_handled_by_email(self, obj):
        u = getattr(obj, "handled_by", None)
        return getattr(u, "email", "") if u else ""


class SupportRequestHandleSerializer(serializers.ModelSerializer):
    """
    Used by platform admins to change status and mark handled.
    """
    class Meta:
        model = SupportRequest
        fields = ["status"]
