from rest_framework import serializers

from user_accounts.models import BusinessDataImport


class BusinessDataImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessDataImport
        fields = [
            "id",
            "business",
            "import_type",
            "status",
            "source_system",
            "original_filename",
            "file_size_bytes",
            "column_mapping",
            "headers",
            "sample_rows",
            "total_rows",
            "valid_rows",
            "skipped_rows",
            "error_count",
            "errors",
            "summary",
            "created_by",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields
