from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_invite import PMInvite


class PMInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMInvite
        fields = [
            "id",
            "business",
            "unit",
            "created_by",
            "email",
            "code",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business", "created_by", "code", "created_at", "updated_at"]
