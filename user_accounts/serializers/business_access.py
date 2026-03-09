# backend/user_accounts/serializers/business_access.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.business_access import BusinessAccessControl


class BusinessAccessControlSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessAccessControl
        fields = [
            "id",
            "business",
            "is_locked",
            "lock_reason",
            "locked_at",
            "locked_by",
            "last_unlock_requested_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "locked_at", "locked_by", "created_at", "updated_at"]
