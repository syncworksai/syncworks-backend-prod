from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from .personal_finance import FinanceAccount, FinanceLiability


class FinanceDebtPayment(models.Model):
    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        PLAID = "PLAID", "Connected account"
        IMPORTED = "IMPORTED", "Imported"

    class Status(models.TextChoices):
        POSTED = "POSTED", "Posted"
        PENDING = "PENDING", "Pending"
        REVERSED = "REVERSED", "Reversed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_debt_payments")
    liability = models.ForeignKey(FinanceLiability, on_delete=models.CASCADE, related_name="payments")
    account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="debt_payments")
    funding_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="funded_debt_payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.POSTED)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    principal_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    interest_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    fee_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    estimated_interest_saved_next_30_days = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    provider_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date", "-id"]
        indexes = [
            models.Index(fields=["user", "-payment_date"]),
            models.Index(fields=["liability", "-payment_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider_reference"],
                condition=~models.Q(provider_reference=""),
                name="uniq_user_finance_debt_payment_provider_ref",
            )
        ]
