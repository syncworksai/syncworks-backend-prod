from __future__ import annotations

from django.db import models


class StripeWebhookEvent(models.Model):
    """Persistent idempotency ledger for verified Stripe webhook events.

    Stripe can retry the same event multiple times. `stripe_event_id` is globally
    unique so business logic can safely short-circuit duplicates before creating
    a second invoice/payment/subscription side effect.
    """

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        IGNORED = "IGNORED", "Ignored"
        FAILED = "FAILED", "Failed"

    stripe_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=255, blank=True, default="", db_index=True)
    endpoint = models.CharField(max_length=120, blank=True, default="", db_index=True)
    object_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    livemode = models.BooleanField(default=False)
    api_version = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    attempts = models.PositiveIntegerField(default=1)
    last_error = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["endpoint", "event_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.stripe_event_id} ({self.event_type or 'unknown'})"
