from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class PartnerWorkTicket(models.Model):
    class Status(models.TextChoices):
        OFFERED = "OFFERED", "Offered"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        SCHEDULED = "SCHEDULED", "Scheduled"
        EN_ROUTE = "EN_ROUTE", "En route"
        ON_SITE = "ON_SITE", "On site"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        BLOCKED = "BLOCKED", "Blocked"
        AWAITING_REVIEW = "AWAITING_REVIEW", "Awaiting hiring-business review"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    relationship = models.ForeignKey(
        "user_accounts.BusinessPartnerRelationship",
        on_delete=models.PROTECT,
        related_name="work_tickets",
    )
    source_ticket = models.OneToOneField(
        "user_accounts.Ticket",
        on_delete=models.PROTECT,
        related_name="partner_work_ticket",
    )
    hiring_business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="partner_work_sent",
    )
    partner_business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="partner_work_received",
    )
    assigned_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_work_assignments",
        null=True,
        blank=True,
    )

    title = models.CharField(max_length=200)
    scope = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.OFFERED,
        db_index=True,
    )

    service_address = models.CharField(max_length=255, blank=True, default="")
    service_zip = models.CharField(max_length=10, blank=True, default="")
    access_instructions = models.TextField(blank=True, default="")

    share_customer_contact = models.BooleanField(default=False)
    customer_contact_name = models.CharField(
        max_length=180,
        blank=True,
        default="",
    )
    customer_contact_email = models.EmailField(blank=True, default="")
    customer_contact_phone = models.CharField(
        max_length=32,
        blank=True,
        default="",
    )

    agreed_amount_cents = models.PositiveBigIntegerField(default=0)
    partner_internal_cost_cents = models.PositiveBigIntegerField(default=0)
    partner_internal_notes = models.TextField(blank=True, default="")
    hiring_business_notes = models.TextField(blank=True, default="")
    shared_updates = models.TextField(blank=True, default="")
    completion_summary = models.TextField(blank=True, default="")
    blocked_reason = models.TextField(blank=True, default="")

    offered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_work_offered",
        null=True,
        blank=True,
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_work_accepted",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_work_reviewed",
        null=True,
        blank=True,
    )

    offered_at = models.DateTimeField(default=timezone.now)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(
                fields=["hiring_business", "status", "updated_at"],
                name="ua_pwork_hiring_status_idx",
            ),
            models.Index(
                fields=["partner_business", "status", "updated_at"],
                name="ua_pwork_partner_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Partner work {self.id}: {self.hiring_business_id} -> "
            f"{self.partner_business_id}"
        )
