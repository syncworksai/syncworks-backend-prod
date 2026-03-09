from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class Invoice(models.Model):
    class Kind(models.TextChoices):
        JOB = "JOB", "Job Invoice"
        CASH_FEE = "CASH_FEE", "Cash Fee Invoice"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PAID = "PAID", "Paid"
        OVERDUE = "OVERDUE", "Overdue"
        VOID = "VOID", "Void"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="invoices")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.JOB)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    currency = models.CharField(max_length=10, default="usd")
    amount_cents = models.PositiveIntegerField(default=0)

    # for monthly cash fee billing
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    due_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_invoices",
    )

    created_at = models.DateTimeField(default=timezone.now)
    paid_at = models.DateTimeField(null=True, blank=True)

    memo = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["business", "kind", "status"]),
            models.Index(fields=["kind", "period_start", "period_end"]),
            models.Index(fields=["due_date", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invoice #{self.id} {self.kind} {self.status}"