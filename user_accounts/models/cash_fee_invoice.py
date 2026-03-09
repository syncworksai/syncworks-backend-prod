from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class CashFeeInvoice(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PAID = "PAID", "Paid"
        OVERDUE = "OVERDUE", "Overdue"
        VOID = "VOID", "Void"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="cash_fee_invoices")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    currency = models.CharField(max_length=10, default="usd")
    amount_cents = models.PositiveIntegerField(default=0)

    # monthly fee period
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    due_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_cash_fee_invoices",
    )

    memo = models.CharField(max_length=255, blank=True, default="")

    # ----------------------------
    # ✅ Stripe collection tracking
    # ----------------------------
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    stripe_charge_id = models.CharField(max_length=255, blank=True, default="")

    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["period_start", "period_end"]),
            models.Index(fields=["due_date", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "period_start", "period_end"],
                name="uniq_cash_fee_invoice_business_period",
            )
        ]
        ordering = ["-created_at"]

    def mark_overdue_if_needed(self) -> None:
        try:
            if self.status == self.Status.OPEN and self.due_date and timezone.localdate() > self.due_date:
                self.status = self.Status.OVERDUE
        except Exception:
            pass

    def __str__(self) -> str:
        return f"CashFeeInvoice #{self.id} {self.status}"