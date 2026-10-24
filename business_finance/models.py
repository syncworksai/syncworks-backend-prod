from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models
from django.utils import timezone


class BusinessExpense(models.Model):
    class Category(models.TextChoices):
        LABOR = "LABOR", "Labor"
        MATERIAL = "MATERIAL", "Materials"
        SUBCONTRACTOR = "SUBCONTRACTOR", "Subcontractor"
        OVERHEAD = "OVERHEAD", "Overhead"
        EQUIPMENT = "EQUIPMENT", "Equipment"
        MARKETING = "MARKETING", "Marketing"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        INCURRED = "INCURRED", "Incurred"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="finance_expenses")
    ticket = models.ForeignKey("user_accounts.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_costs")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INCURRED)
    description = models.CharField(max_length=220)
    vendor = models.CharField(max_length=160, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False)
    incurred_on = models.DateField(default=timezone.localdate)
    due_on = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="business_finance_expenses_created")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-incurred_on", "-id"]
        indexes = [
            models.Index(fields=["business", "incurred_on"], name="bf_exp_business_date"),
            models.Index(fields=["business", "ticket"], name="bf_exp_business_job"),
        ]

    def save(self, *args, **kwargs):
        self.amount = (self.quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class JobCostReview(models.Model):
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="finance_job_reviews")
    ticket = models.OneToOneField("user_accounts.Ticket", on_delete=models.CASCADE, related_name="finance_cost_review")
    costs_complete = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-reviewed_at", "-id"]


class BusinessFinanceSettings(models.Model):
    business = models.OneToOneField("user_accounts.Business", on_delete=models.CASCADE, related_name="finance_settings")
    opening_cash_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    opening_cash_date = models.DateField(null=True, blank=True)
    expenses_reconciled_through = models.DateField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class CashForecastItem(models.Model):
    class Direction(models.TextChoices):
        IN = "IN", "Expected inflow"
        OUT = "OUT", "Expected outflow"

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        SETTLED = "SETTLED", "Settled elsewhere"
        CANCELLED = "CANCELLED", "Cancelled"

    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="cash_forecast_items")
    description = models.CharField(max_length=220)
    direction = models.CharField(max_length=3, choices=Direction.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    expected_on = models.DateField()
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expected_on", "id"]
        indexes = [models.Index(fields=["business", "expected_on"], name="bf_forecast_business_day")]
