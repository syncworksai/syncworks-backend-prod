from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.assets import TrackableAsset
from user_accounts.models.resources import BusinessResource
from user_accounts.models.tickets import Ticket


class TicketRequirement(models.Model):
    class RequirementType(models.TextChoices):
        CUSTOMER_APPROVAL = "CUSTOMER_APPROVAL", "Customer Approval"
        CUSTOMER_RESPONSE = "CUSTOMER_RESPONSE", "Customer Response"
        PAYMENT = "PAYMENT", "Payment"
        DOCUMENT = "DOCUMENT", "Document"
        PART = "PART", "Part or Material"
        ASSET = "ASSET", "Asset"
        RESOURCE = "RESOURCE", "Resource"
        STAFF = "STAFF", "Staff"
        INSPECTION = "INSPECTION", "Inspection"
        EXTERNAL = "EXTERNAL", "External Dependency"
        CUSTOM = "CUSTOM", "Custom"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        SATISFIED = "SATISFIED", "Satisfied"
        WAIVED = "WAIVED", "Waived"
        CANCELLED = "CANCELLED", "Cancelled"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="requirements",
    )
    requirement_type = models.CharField(
        max_length=32,
        choices=RequirementType.choices,
        default=RequirementType.CUSTOM,
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.NORMAL,
    )
    blocks_progress = models.BooleanField(default=True)
    due_at = models.DateTimeField(null=True, blank=True)
    satisfied_at = models.DateTimeField(null=True, blank=True)
    satisfied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_requirements_satisfied",
    )
    asset = models.ForeignKey(
        TrackableAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_requirements",
    )
    resource = models.ForeignKey(
        BusinessResource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_requirements",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_requirements_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-blocks_progress", "due_at", "id"]
        indexes = [
            models.Index(
                fields=["ticket", "status", "blocks_progress"],
                name="ua_req_ticket_status_idx",
            ),
            models.Index(
                fields=["status", "severity", "due_at"],
                name="ua_req_priority_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Ticket {self.ticket_id}: {self.title}"


class TicketDependency(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="dependencies",
    )
    depends_on_ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="dependent_tickets",
    )
    description = models.CharField(max_length=255, blank=True, default="")
    is_blocking = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_dependencies_created",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["ticket_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "depends_on_ticket"],
                name="ua_ticket_dependency_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(ticket=models.F("depends_on_ticket")),
                name="ua_ticket_no_self_dependency",
            ),
        ]
        indexes = [
            models.Index(
                fields=["ticket", "is_blocking"],
                name="ua_ticket_dependency_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Ticket {self.ticket_id} depends on {self.depends_on_ticket_id}"
