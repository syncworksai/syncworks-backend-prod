from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PartnerWorkEstimate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    work_ticket = models.ForeignKey(
        "user_accounts.PartnerWorkTicket",
        on_delete=models.CASCADE,
        related_name="estimates",
    )
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    title = models.CharField(max_length=200, blank=True, default="")
    scope = models.TextField(blank=True, default="")
    line_items = models.JSONField(default=list, blank=True)
    subtotal_cents = models.PositiveBigIntegerField(default=0)
    tax_cents = models.PositiveBigIntegerField(default=0)
    total_cents = models.PositiveBigIntegerField(default=0)
    estimated_days = models.PositiveIntegerField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    partner_notes = models.TextField(blank=True, default="")
    hiring_business_notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_estimates_created",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_estimates_reviewed",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-revision", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_ticket", "revision"],
                name="ua_unique_partner_estimate_revision",
            ),
        ]
        indexes = [
            models.Index(
                fields=["work_ticket", "status", "created_at"],
                name="ua_pestimate_work_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Estimate {self.work_ticket_id} r{self.revision}"


class PartnerWorkChangeOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    work_ticket = models.ForeignKey(
        "user_accounts.PartnerWorkTicket",
        on_delete=models.CASCADE,
        related_name="change_orders",
    )
    sequence = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    title = models.CharField(max_length=200)
    reason = models.TextField(blank=True, default="")
    scope_delta = models.TextField(blank=True, default="")
    line_items = models.JSONField(default=list, blank=True)

    partner_amount_delta_cents = models.BigIntegerField(default=0)
    customer_amount_delta_cents = models.BigIntegerField(default=0)
    schedule_days_delta = models.IntegerField(default=0)

    partner_notes = models.TextField(blank=True, default="")
    hiring_business_notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_change_orders_created",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_change_orders_reviewed",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sequence", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_ticket", "sequence"],
                name="ua_unique_partner_change_sequence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["work_ticket", "status", "created_at"],
                name="ua_pchange_work_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Change order {self.work_ticket_id} #{self.sequence}"
