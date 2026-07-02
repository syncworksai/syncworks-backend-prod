from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class BusinessProject(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        ON_HOLD = "ON_HOLD", "On hold"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class BillingMode(models.TextChoices):
        COMBINED = "COMBINED", "Combined invoice"
        SEPARATE = "SEPARATE", "Separate child invoices"
        MILESTONE = "MILESTONE", "Milestone billing"

    class ProgressMode(models.TextChoices):
        EQUAL = "EQUAL", "Equal child weighting"
        WEIGHTED = "WEIGHTED", "Custom child weighting"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="projects")
    business_customer = models.ForeignKey(
        "user_accounts.BusinessCustomer", on_delete=models.SET_NULL,
        related_name="projects", null=True, blank=True,
    )
    primary_ticket = models.ForeignKey(
        "user_accounts.Ticket", on_delete=models.SET_NULL,
        related_name="primary_for_projects", null=True, blank=True,
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    billing_mode = models.CharField(max_length=20, choices=BillingMode.choices, default=BillingMode.COMBINED)
    progress_mode = models.CharField(max_length=20, choices=ProgressMode.choices, default=ProgressMode.EQUAL)
    customer_status_note = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="business_projects_created", null=True, blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="business_projects_updated", null=True, blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["business", "status", "updated_at"], name="ua_project_biz_status_idx"),
            models.Index(fields=["business", "business_customer", "updated_at"], name="ua_project_customer_idx"),
        ]
