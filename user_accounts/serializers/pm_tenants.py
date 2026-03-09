from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_tenant import PMTenant


class PMTenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTenant
        fields = [
            "id",
            "business",
            "property",
            "unit",
            "first_name",
            "last_name",
            "email",
            "phone",
            "status",
            "section8",
            "voucher_id",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]
