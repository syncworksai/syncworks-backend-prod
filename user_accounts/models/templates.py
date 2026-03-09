# backend/user_accounts/models/templates.py
from __future__ import annotations

from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class DocumentTemplate(models.Model):
    """
    Business-scoped document templates (quotes, invoices, work orders, etc.)
    These are used by /doc-templates/ endpoints.
    """

    class TemplateType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        QUOTE = "QUOTE", "Quote"
        INVOICE = "INVOICE", "Invoice"
        WORK_ORDER = "WORK_ORDER", "Work Order"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="document_templates",
    )

    name = models.CharField(max_length=160)
    template_type = models.CharField(
        max_length=30,
        choices=TemplateType.choices,
        default=TemplateType.GENERAL,
    )

    # Free-form template body (Markdown or plain text)
    body = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        unique_together = [("business", "name")]

    def __str__(self) -> str:
        return f"{self.name} (biz={self.business_id})"
