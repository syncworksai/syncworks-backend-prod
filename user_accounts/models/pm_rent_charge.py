from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class PMRentCharge(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    # Always scope to business (same pattern as your PM models)
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="pm_rent_charges")

    property = models.ForeignKey("user_accounts.PMProperty", on_delete=models.CASCADE, related_name="rent_charges")
    unit = models.ForeignKey("user_accounts.PMUnit", on_delete=models.CASCADE, related_name="rent_charges")
    tenant = models.ForeignKey("user_accounts.PMTenant", on_delete=models.CASCADE, related_name="rent_charges")

    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    late_fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True, default="")

    # Stripe
    stripe_checkout_url = models.URLField(blank=True, default="")
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_rent_charges"
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-due_date", "-id"]
        indexes = [
            models.Index(fields=["business", "due_date"]),
            models.Index(fields=["business", "status"]),
            models.Index(fields=["tenant", "due_date"]),
        ]

    @property
    def total_due(self) -> Decimal:
        return (self.amount or Decimal("0.00")) + (self.late_fee_amount or Decimal("0.00"))

    @property
    def balance_due(self) -> Decimal:
        bd = self.total_due - (self.paid_amount or Decimal("0.00"))
        return bd if bd > 0 else Decimal("0.00")

    def recompute_status(self) -> None:
        if self.status == self.Status.VOID:
            return
        if self.paid_amount >= self.total_due and self.total_due > 0:
            self.status = self.Status.PAID
        elif self.paid_amount > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.OPEN
