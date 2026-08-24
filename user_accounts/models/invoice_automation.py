from __future__ import annotations

from django.db import models

from .business import Business


class InvoiceAutomationSettings(models.Model):
    class DueTerms(models.TextChoices):
        DUE_ON_RECEIPT = "DUE_ON_RECEIPT", "Due on receipt"
        NET_7 = "NET_7", "Net 7"
        NET_15 = "NET_15", "Net 15"
        NET_30 = "NET_30", "Net 30"
        NET_45 = "NET_45", "Net 45"
        CUSTOM = "CUSTOM", "Custom"

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="invoice_automation_settings")
    auto_send_invoices = models.BooleanField(default=False)
    due_terms = models.CharField(max_length=24, choices=DueTerms.choices, default=DueTerms.NET_15)
    custom_due_days = models.PositiveIntegerField(default=14)

    auto_reminders_enabled = models.BooleanField(default=False)
    reminder_before_due_days = models.PositiveIntegerField(default=3)
    reminder_on_due_date = models.BooleanField(default=True)
    reminder_after_due_days = models.JSONField(default=list, blank=True)

    pause_new_non_emergency_work_when_overdue = models.BooleanField(default=False)
    overdue_pause_threshold_days = models.PositiveIntegerField(default=30)
    overdue_pause_threshold_cents = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["business_id"]

    def due_days(self) -> int:
        mapping = {
            self.DueTerms.DUE_ON_RECEIPT: 0,
            self.DueTerms.NET_7: 7,
            self.DueTerms.NET_15: 15,
            self.DueTerms.NET_30: 30,
            self.DueTerms.NET_45: 45,
        }
        if self.due_terms == self.DueTerms.CUSTOM:
            return max(0, min(365, int(self.custom_due_days or 0)))
        return mapping.get(self.due_terms, 15)
