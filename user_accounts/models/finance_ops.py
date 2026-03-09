# backend/user_accounts/models/finance_ops.py
from __future__ import annotations

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class FinanceSnapshot(models.Model):
    """
    Stores the user's current finance state (cash-flow snapshot).
    JSON keeps it flexible as the schema evolves.

    Example payload:
      {
        "income_streams": [{"name":"W2","amount_monthly":4000}],
        "monthly_income": {"min": 3800, "avg": 4200, "max": 4600},
        "fixed_obligations": [{"name":"Rent","amount":1500}],
        "variable_spend": {"min": 800, "avg": 1100, "max": 1400},
        "cash_on_hand": 1200,
        "debts": [{"name":"Card A","apr":24.99,"balance":3200,"minimum":95}],
        "credit_score": 680
      }
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="finance_snapshots")
    payload = models.JSONField(default=dict, blank=True)

    # Optional "label" for UI
    label = models.CharField(max_length=120, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"FinanceSnapshot(user_id={self.user_id}, id={self.id})"


class FinancePlan(models.Model):
    """
    Stores prior plans + outcomes (Memory / History).
    The 'sections' field holds the plan structure:
      - immediate (7-30)
      - tactical (3-6 mo)
      - strategic (12+ mo)
      - top_3_priorities (ranked actions)
      - systems/templates used
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        COMPLETE = "COMPLETE", "Complete"
        ARCHIVED = "ARCHIVED", "Archived"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="finance_plans")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # A short title like "January Reset" or "Debt Paydown Sprint"
    title = models.CharField(max_length=160, blank=True, default="")

    # Structured plan content (flexible)
    sections = models.JSONField(default=dict, blank=True)

    # Outcome notes after execution
    outcome_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"FinancePlan(user_id={self.user_id}, id={self.id}, status={self.status})"
