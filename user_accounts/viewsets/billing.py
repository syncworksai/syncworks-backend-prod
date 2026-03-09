# backend/user_accounts/models/billing.py
from __future__ import annotations

from decimal import Decimal
from django.db import models
from django.utils import timezone

from .tickets import Ticket


class Invoice(models.Model):
    """
    Invoice generated from a Ticket.

    Payment flow (production):
      - Customer pays via Stripe Checkout (mode=payment)
      - Platform fee collected via application_fee_amount (default 1%)
      - Remaining funds routed to connected account (destination charge)
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    class PaymentMethod(models.TextChoices):
        CARD = "CARD", "Card"
        CASH = "CASH", "Cash"
        OTHER = "OTHER", "Other"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    title = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    due_date = models.DateField(null=True, blank=True)

    # Payment tracking (local truth)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CARD)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    paid_at = models.DateTimeField(null=True, blank=True)

    # Platform fee (1% default). Stored so KPI math is deterministic.
    platform_fee_rate_bps = models.PositiveIntegerField(default=100)  # 100 bps = 1.00%
    platform_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    platform_fee_collected = models.BooleanField(default=False)
    platform_fee_collected_at = models.DateTimeField(null=True, blank=True)

    # Stripe reconciliation fields (do NOT store card details)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, default="")
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    stripe_charge_id = models.CharField(max_length=255, blank=True, default="")
    stripe_transfer_id = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def recompute_platform_fee(self) -> None:
        rate = Decimal(self.platform_fee_rate_bps) / Decimal(10000)
        self.platform_fee_amount = (Decimal(self.total) * rate).quantize(Decimal("0.01"))

    def mark_paid(self, *, method: str | None = None) -> None:
        if method:
            self.payment_method = method
        self.status = self.Status.PAID
        self.amount_paid = self.total
        self.paid_at = timezone.now()
        self.recompute_platform_fee()

        # Card payment means fee is collected automatically
        if self.payment_method == self.PaymentMethod.CARD:
            self.platform_fee_collected = True
            self.platform_fee_collected_at = timezone.now()

    def mark_platform_fee_collected(self) -> None:
        self.platform_fee_collected = True
        self.platform_fee_collected_at = timezone.now()

    def save(self, *args, **kwargs):
        try:
            self.recompute_platform_fee()
        except Exception:
            pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice #{self.id} ({self.status})"
