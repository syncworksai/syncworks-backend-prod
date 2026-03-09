# backend/user_accounts/models/pm_document.py
from __future__ import annotations

import builtins
import os

from django.conf import settings
from django.db import models

from user_accounts.models.business import Business
from user_accounts.models.pm_property import PMProperty
from user_accounts.models.pm_unit import PMUnit
from user_accounts.models.pm_tenant import PMTenant


class PMDocument(models.Model):
    DOC_GENERAL = "GENERAL"
    DOC_LEASE = "LEASE"
    DOC_PM_AGREEMENT = "PM_AGREEMENT"
    DOC_APPLICATION = "APPLICATION"
    DOC_SECTION8 = "SECTION8"
    DOC_INSPECTION = "INSPECTION"
    DOC_NOTICE = "NOTICE"
    DOC_RECEIPT = "RECEIPT"

    DOC_TYPE_CHOICES = [
        (DOC_GENERAL, "General"),
        (DOC_LEASE, "Lease"),
        (DOC_PM_AGREEMENT, "PM Agreement"),
        (DOC_APPLICATION, "Application"),
        (DOC_SECTION8, "Section 8"),
        (DOC_INSPECTION, "Inspection"),
        (DOC_NOTICE, "Notice"),
        (DOC_RECEIPT, "Receipt"),
    ]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_documents")

    # NOTE: this field name MUST stay "property" because the frontend posts "property"
    # but it shadows Python's @property decorator, so we use builtins.property below.
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="documents")
    unit = models.ForeignKey(PMUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    tenant = models.ForeignKey(PMTenant, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")

    doc_type = models.CharField(max_length=32, choices=DOC_TYPE_CHOICES, default=DOC_GENERAL)

    title = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # Private = PM staff only. Public = tenant portal (later wiring)
    private = models.BooleanField(default=True)

    file = models.FileField(upload_to="pm/documents/%Y/%m/", blank=False, null=False)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_documents_uploaded",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "property", "doc_type"]),
            models.Index(fields=["business", "unit"]),
            models.Index(fields=["business", "tenant"]),
        ]
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return f"PMDocument({self.id}) {self.title or self.file_name}"

    @builtins.property
    def file_name(self) -> str:
        try:
            return os.path.basename(self.file.name or "")
        except Exception:
            return ""

    @builtins.property
    def file_ext(self) -> str:
        name = self.file_name
        if "." not in name:
            return ""
        return name.split(".")[-1].lower()
