from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class FinanceConnection(models.Model):
    class Provider(models.TextChoices):
        PLAID = "PLAID", "Plaid"
        MANUAL = "MANUAL", "Manual"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        NEEDS_ATTENTION = "NEEDS_ATTENTION", "Needs attention"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_connections")
    provider = models.CharField(max_length=24, choices=Provider.choices, default=Provider.PLAID)
    provider_item_id = models.CharField(max_length=255, blank=True, default="")
    institution_id = models.CharField(max_length=120, blank=True, default="")
    institution_name = models.CharField(max_length=180, blank=True, default="")
    encrypted_access_token = models.TextField(blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACTIVE)
    cursor = models.TextField(blank=True, default="")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider", "provider_item_id"], name="uniq_user_finance_provider_item"),
        ]


class FinanceAccount(models.Model):
    class Kind(models.TextChoices):
        CHECKING = "CHECKING", "Checking"
        SAVINGS = "SAVINGS", "Savings"
        CREDIT_CARD = "CREDIT_CARD", "Credit card"
        MORTGAGE = "MORTGAGE", "Mortgage"
        STUDENT_LOAN = "STUDENT_LOAN", "Student loan"
        AUTO_LOAN = "AUTO_LOAN", "Auto loan"
        PERSONAL_LOAN = "PERSONAL_LOAN", "Personal loan"
        INVESTMENT = "INVESTMENT", "Investment"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_accounts")
    connection = models.ForeignKey(FinanceConnection, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts")
    provider_account_id = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=180)
    official_name = models.CharField(max_length=255, blank=True, default="")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    mask = models.CharField(max_length=12, blank=True, default="")
    currency = models.CharField(max_length=8, default="USD")
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    available_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_manual = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider_account_id"], condition=~models.Q(provider_account_id=""), name="uniq_user_finance_provider_account"),
        ]


class FinanceLiability(models.Model):
    class Kind(models.TextChoices):
        CREDIT_CARD = "CREDIT_CARD", "Credit card"
        MORTGAGE = "MORTGAGE", "Mortgage"
        STUDENT_LOAN = "STUDENT_LOAN", "Student loan"
        AUTO_LOAN = "AUTO_LOAN", "Auto loan"
        PERSONAL_LOAN = "PERSONAL_LOAN", "Personal loan"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_liabilities")
    account = models.OneToOneField(FinanceAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="liability")
    name = models.CharField(max_length=180)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    lender = models.CharField(max_length=180, blank=True, default="")
    outstanding_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    original_principal = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    minimum_payment = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    next_payment_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    next_payment_date = models.DateField(null=True, blank=True)
    apr = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    interest_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    origination_date = models.DateField(null=True, blank=True)
    maturity_date = models.DateField(null=True, blank=True)
    payoff_target_date = models.DateField(null=True, blank=True)
    last_payment_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    property_address = models.CharField(max_length=320, blank=True, default="")
    escrow_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_manual = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_payment_date", "name"]


class FinanceObligation(models.Model):
    class Category(models.TextChoices):
        HOUSING = "HOUSING", "Housing"
        UTILITIES = "UTILITIES", "Utilities"
        INSURANCE = "INSURANCE", "Insurance"
        TRANSPORTATION = "TRANSPORTATION", "Transportation"
        SUBSCRIPTIONS = "SUBSCRIPTIONS", "Subscriptions"
        DEBT = "DEBT", "Debt"
        CHILDCARE = "CHILDCARE", "Childcare"
        HEALTH = "HEALTH", "Health"
        TAX = "TAX", "Tax"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_obligations")
    linked_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="obligations")
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.OTHER)
    merchant = models.CharField(max_length=180, blank=True, default="")
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    minimum_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    due_day = models.PositiveSmallIntegerField(null=True, blank=True)
    next_due_date = models.DateField(null=True, blank=True)
    autopay = models.BooleanField(default=False)
    recurring = models.BooleanField(default=True)
    cadence = models.CharField(max_length=32, blank=True, default="MONTHLY")
    active = models.BooleanField(default=True)
    is_manual = models.BooleanField(default=True)
    provider_stream_id = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_due_date", "due_day", "name"]


class FinanceTransaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_transactions")
    account = models.ForeignKey(FinanceAccount, on_delete=models.CASCADE, related_name="transactions")
    provider_transaction_id = models.CharField(max_length=255, blank=True, default="")
    merchant_name = models.CharField(max_length=255, blank=True, default="")
    description = models.CharField(max_length=320, blank=True, default="")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    date = models.DateField()
    pending = models.BooleanField(default=False)
    category_primary = models.CharField(max_length=100, blank=True, default="")
    category_detailed = models.CharField(max_length=160, blank=True, default="")
    is_income = models.BooleanField(default=False)
    is_transfer = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["user", "-date"]), models.Index(fields=["user", "category_primary"])]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider_transaction_id"], condition=~models.Q(provider_transaction_id=""), name="uniq_user_finance_provider_transaction"),
        ]


class FinanceGoal(models.Model):
    class Kind(models.TextChoices):
        EMERGENCY_FUND = "EMERGENCY_FUND", "Emergency fund"
        DEBT_PAYOFF = "DEBT_PAYOFF", "Debt payoff"
        SAVINGS = "SAVINGS", "Savings"
        PURCHASE = "PURCHASE", "Purchase"
        INVESTMENT = "INVESTMENT", "Investment"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="finance_goals")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    name = models.CharField(max_length=180)
    target_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    current_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    target_date = models.DateField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "target_date", "name"]
