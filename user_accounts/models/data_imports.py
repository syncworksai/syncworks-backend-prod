from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class BusinessDataImport(models.Model):
    class ImportType(models.TextChoices):
        CUSTOMERS = "CUSTOMERS", "Customers"
        TICKETS = "TICKETS", "Tickets"

    class Status(models.TextChoices):
        PREVIEWED = "PREVIEWED", "Previewed"
        READY = "READY", "Ready"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        COMPLETED_WITH_ERRORS = (
            "COMPLETED_WITH_ERRORS",
            "Completed with errors",
        )
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="data_imports",
    )
    import_type = models.CharField(max_length=20, choices=ImportType.choices)
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PREVIEWED,
        db_index=True,
    )
    source_system = models.CharField(max_length=100, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size_bytes = models.PositiveIntegerField(default=0)
    column_mapping = models.JSONField(default=dict, blank=True)
    headers = models.JSONField(default=list, blank=True)
    sample_rows = models.JSONField(default=list, blank=True)
    payload_rows = models.JSONField(default=list, blank=True)

    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    matched_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="business_data_imports_created",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["business", "import_type", "created_at"],
                name="ua_import_biz_type_idx",
            ),
            models.Index(
                fields=["business", "status", "created_at"],
                name="ua_import_biz_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.business_id}:{self.import_type}:{self.id}"
