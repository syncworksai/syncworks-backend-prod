from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PMWorkOrder(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        ON_HOLD = "ON_HOLD", "On Hold"
        COMPLETED = "COMPLETED", "Completed"
        CANCELED = "CANCELED", "Canceled"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    # ✅ How it was assigned
    class AssignmentMode(models.TextChoices):
        NONE = "NONE", "None"
        TECH = "TECH", "Technician"
        MARKETPLACE = "MARKETPLACE", "Marketplace"

    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="pm_workorders",
    )

    # Optional links
    property = models.ForeignKey(
        "user_accounts.PMProperty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )
    unit = models.ForeignKey(
        "user_accounts.PMUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )
    tenant = models.ForeignKey(
        "user_accounts.PMTenant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workorders",
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    due_date = models.DateField(null=True, blank=True)

    # legacy email field (keep)
    assigned_to_email = models.EmailField(blank=True, default="")

    # ✅ NEW assignment fields (migration 0041)
    assignment_mode = models.CharField(
        max_length=20,
        choices=AssignmentMode.choices,
        default=AssignmentMode.NONE,
        db_index=True,
    )

    assigned_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_workorders_assigned",
    )

    marketplace_ticket = models.ForeignKey(
        "user_accounts.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_workorders",
    )

    marketplace_requested_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_workorders_created",
    )

    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "due_date"]),
            models.Index(fields=["business", "assignment_mode"]),
        ]

    def __str__(self) -> str:
        return f"[{self.business_id}] {self.title}"
