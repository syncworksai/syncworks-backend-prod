# backend/user_accounts/serializers/pm_documents.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_document import PMDocument


class PMDocumentSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(read_only=True)
    file_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = PMDocument
        fields = [
            "id",
            "business",
            "property",
            "unit",
            "tenant",
            "doc_type",
            "title",
            "notes",
            "private",
            "file",
            "file_name",
            "file_url",
            "download_url",
            "url",
            "uploaded_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "business",
            "uploaded_by",
            "file_name",
            "file_url",
            "download_url",
            "url",
            "created_at",
            "updated_at",
        ]

    def _abs(self, rel: str | None) -> str | None:
        if not rel:
            return None
        req = self.context.get("request")
        if not req:
            return rel
        return req.build_absolute_uri(rel)

    def get_file_url(self, obj: PMDocument):
        try:
            return self._abs(obj.file.url if obj.file else None)
        except Exception:
            return None

    def get_download_url(self, obj: PMDocument):
        return self.get_file_url(obj)

    def get_url(self, obj: PMDocument):
        return self.get_file_url(obj)
