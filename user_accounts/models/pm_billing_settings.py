# backend/user_accounts/models/pm_billing_settings.py
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class PMBillingSettings(models.Model):
    """
    One settings row per Business (scoped by X-Business-Id).
    Drives rent due, grace, late fee rules, payout approval rules, mgmt fee, and maintenance hard-stop.

    NOTE: We store business_id as an int to stay compatible with your existing X-Business-Id pattern.
    """

    business_id = models.PositiveIntegerField(unique=True, db_index=True)

    # Rent / billing cadence defaults
    rent_due_day = models.PositiveSmallIntegerField(default=1)  # day-of-month (1..28 recommended)
    grace_days = models.PositiveSmallIntegerField(default=5)

    # Late fee rule
    late_fee_enabled = models.BooleanField(default=True)
    late_fee_type = models.CharField(
        max_length=16,
        choices=[("FLAT", "Flat"), ("PCT", "Percent")],
        default="FLAT",
    )
    late_fee_flat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("50.00"))
    late_fee_percent = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.050"))  # 5%

    # ---------------------------
    # Management fee (PM company)
    # ---------------------------
    mgmt_fee_enabled = models.BooleanField(default=True)
    mgmt_fee_type = models.CharField(
        max_length=16,
        choices=[("FLAT", "Flat"), ("PCT", "Percent")],
        default="PCT",
    )
    mgmt_fee_flat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    mgmt_fee_percent = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.100"))  # 10%

    # ---------------------------------------
    # Maintenance hard-stop & rent deductions
    # ---------------------------------------
    maintenance_auto_cover_enabled = models.BooleanField(default=True)
    maintenance_auto_cover_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("50.00")
    )  # e.g., $30 lightbulb covered by PM and/or deducted from rent per rules below

    maintenance_deduct_from_rent_enabled = models.BooleanField(default=True)
    maintenance_deduct_requires_approval_over_limit = models.BooleanField(default=True)

    # ---------------------------
    # Payout control / security
    # ---------------------------
    payout_requires_manual_approval = models.BooleanField(default=True)
    payout_auto_approve_if_current = models.BooleanField(default=False)

    # Automation toggles
    auto_email_enabled = models.BooleanField(default=True)
    email_send_on_due = models.BooleanField(default=True)
    email_send_on_past_due = models.BooleanField(default=True)
    email_send_on_late_fee = models.BooleanField(default=True)

    # Reminder schedule (days relative to due date)
    remind_days_before_due = models.PositiveSmallIntegerField(default=3)
    remind_days_after_due = models.PositiveSmallIntegerField(default=2)

    # Optional "from" name/email (uses settings.DEFAULT_FROM_EMAIL if blank)
    from_name = models.CharField(max_length=120, blank=True, default="")
    from_email = models.EmailField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PM Billing Settings"
        verbose_name_plural = "PM Billing Settings"

    def __str__(self) -> str:
        return f"PMBillingSettings(business_id={self.business_id})"

    def calc_late_fee(self, base_amount: Decimal) -> Decimal:
        if not self.late_fee_enabled:
            return Decimal("0.00")
        if self.late_fee_type == "PCT":
            return (base_amount * (self.late_fee_percent or Decimal("0"))).quantize(Decimal("0.01"))
        return (self.late_fee_flat_amount or Decimal("0")).quantize(Decimal("0.01"))

    def calc_mgmt_fee(self, base_amount: Decimal) -> Decimal:
        if not self.mgmt_fee_enabled:
            return Decimal("0.00")
        if self.mgmt_fee_type == "PCT":
            return (base_amount * (self.mgmt_fee_percent or Decimal("0"))).quantize(Decimal("0.01"))
        return (self.mgmt_fee_flat_amount or Decimal("0")).quantize(Decimal("0.01"))

    def resolved_from_email(self) -> str:
        return self.from_email.strip() or getattr(settings, "DEFAULT_FROM_EMAIL", "")
