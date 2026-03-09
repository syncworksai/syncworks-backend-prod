from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import DocumentTemplate


class DocumentTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentTemplate
        fields = [
            "id",
            "business",
            "name",
            "template_type",
            "body",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]
