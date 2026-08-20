from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .billing import Invoice


class InvoiceEvent(models.Model):
    """Immutable operational timeline for an Invoice.

    This is intentionally separate from payment processor records. It records what
    SyncWorks knows happened to the invoice without pretending an external POS
    payment was processed by SyncWorks.
    """

    class EventType(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        SENT = "SENT", "Sent"
        VIEWED = "VIEWED", "Viewed"
        REMINDER = "REMINDER", "Reminder"
        PAYMENT_RECORDED = "PAYMENT_RECORDED", "Payment recorded"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment failed"
        PAID = "PAID", "Paid"
        VOIDED = "VOIDED", "Voided"
        NOTE = "NOTE", "Note"

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    message = models.CharField(max_length=500, blank=True, default="")
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_source = models.CharField(max_length=40, blank=True, default="")
    external_reference = models.CharField(max_length=255, blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_events_created",
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["invoice", "occurred_at"], name="ua_inv_event_time_idx"),
            models.Index(fields=["event_type", "occurred_at"], name="ua_inv_event_type_idx"),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.invoice_id}: {self.event_type}"
