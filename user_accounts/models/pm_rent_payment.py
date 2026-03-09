# backend/user_accounts/models/pm_rent_payment.py
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class PMRentPayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        ACH = "ACH", "ACH"
        CARD = "CARD", "Card"
        STRIPE = "STRIPE", "Stripe"

    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="pm_rent_payments",
    )
    charge = models.ForeignKey(
        "user_accounts.PMRentCharge",
        on_delete=models.CASCADE,
        related_name="payments",
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=255, blank=True, default="")

    # Stripe metadata (optional)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    stripe_session_id = models.CharField(max_length=255, blank=True, default="")
    stripe_event_id = models.CharField(max_length=255, blank=True, default="")  # ✅ idempotency key

    paid_at = models.DateTimeField(default=timezone.now)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_rent_payments",
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-paid_at", "-id"]
        indexes = [
            models.Index(fields=["business", "paid_at"]),
            models.Index(fields=["charge"]),
            models.Index(fields=["stripe_event_id"]),
            models.Index(fields=["stripe_payment_intent_id"]),
        ]

    def __str__(self) -> str:
        return f"PMRentPayment(id={self.id}, charge={self.charge_id}, amount={self.amount}, method={self.method})"
