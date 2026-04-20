from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.categories import ServiceCategory
from user_accounts.models.service_requests import ServiceRequest


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        ASSIGNED = "ASSIGNED", "Assigned"
        ACCEPTED = "ACCEPTED", "Accepted"
        SCHEDULED = "SCHEDULED", "Scheduled"
        EN_ROUTE = "EN_ROUTE", "En Route"
        ON_SITE = "ON_SITE", "On Site"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"

        NEEDS_QUOTE = "NEEDS_QUOTE", "Needs Quote"
        QUOTED = "QUOTED", "Quote Sent"
        QUOTE_REJECTED = "QUOTE_REJECTED", "Quote Rejected"
        APPROVED = "APPROVED", "Quote Approved"

        AWAITING_APPROVAL = "AWAITING_APPROVAL", "Awaiting Approval"
        COMPLETED = "COMPLETED", "Completed"
        INVOICED = "INVOICED", "Invoiced"
        PAID = "PAID", "Paid"

        CANCELLED = "CANCELLED", "Cancelled"
        CLOSED = "CLOSED", "Closed"

    class PaymentMethod(models.TextChoices):
        CARD = "CARD", "Card"
        CASH = "CASH", "Cash"
        OTHER = "OTHER", "Other"

    service_request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="ticket",
        null=True,
        blank=True,
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tickets_as_customer",
    )

    payer_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_as_payer",
    )

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    assigned_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    assigned_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_assigned",
    )

    is_marketplace = models.BooleanField(default=False)

    service_zip = models.CharField(max_length=10, blank=True, default="")
    service_radius_miles = models.PositiveIntegerField(default=25)
    service_address = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CARD,
        help_text="How the job was paid. CASH triggers monthly 1% fee billing.",
    )

    total_amount_cents = models.PositiveIntegerField(
        default=0,
        help_text="Total ticket/job amount in cents (used for GMV + cash billing).",
    )

    cash_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When SBO confirmed they collected cash (counts into cash GMV).",
    )

    cash_fee_invoiced_month = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="YYYY-MM last month this ticket's cash fee was included in.",
    )

    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_archived",
    )

    created_at = models.DateTimeField(default=timezone.now)

    assigned_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    en_route_at = models.DateTimeField(null=True, blank=True)
    on_site_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    awaiting_approval_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    invoiced_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["assigned_business", "created_at"]),
            models.Index(fields=["assigned_business", "payment_method", "cash_confirmed_at"]),
            models.Index(fields=["payment_method", "cash_confirmed_at"]),
            models.Index(fields=["assigned_business", "archived_at"]),
            models.Index(fields=["is_marketplace", "created_at"]),
            models.Index(fields=["is_marketplace", "status"]),
        ]

    def __str__(self) -> str:
        return f"Ticket #{self.id} ({self.status})"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def ticket_code(self) -> str:
        try:
            prefix = "MP" if bool(self.is_marketplace) else "DT"
            return f"{prefix}-{int(self.id):06d}"
        except Exception:
            return "DT-000000"


class TicketViewEvent(models.Model):
    class EventType(models.TextChoices):
        CUSTOMER_VIEWED = "CUSTOMER_VIEWED", "Customer Viewed"
        BUSINESS_VIEWED = "BUSINESS_VIEWED", "Business Viewed"
        BUSINESS_DECLINED = "BUSINESS_DECLINED", "Business Declined"
        DECLINED_MARKETPLACE = "DECLINED_MARKETPLACE", "Declined Marketplace"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="view_events")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_view_events",
    )

    business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_view_events",
    )

    event_type = models.CharField(max_length=40, choices=EventType.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ticket", "event_type", "-created_at"]),
            models.Index(fields=["ticket", "business", "event_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_id}:{self.event_type}:{self.business_id or '-'}"


class TicketMessage(models.Model):
    class MessageType(models.TextChoices):
        USER = "USER", "User"
        SYSTEM = "SYSTEM", "System"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_messages_sent",
    )

    body = models.TextField(default="")
    type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.USER)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"Msg #{self.id} on Ticket #{self.ticket_id}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_attachments_uploaded",
    )
    file = models.FileField(upload_to="ticket_attachments/")
    filename = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if self.file and not self.filename:
            try:
                self.filename = self.file.name.split("/")[-1]
            except Exception:
                self.filename = ""
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.filename or f"Attachment #{self.id}"


class TicketQuote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="quotes")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_quotes_created",
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    details = models.TextField(blank=True, default="")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_quotes_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_quotes_rejected",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"Quote #{self.id} for Ticket #{self.ticket_id}"