# backend/user_accounts/models/stripe_connect.py
from __future__ import annotations

from django.db import models
from django.utils import timezone

from .business import Business


class StripeConnectProfile(models.Model):
    """
    Stores Stripe Connect Express onboarding + capability snapshots for a Business.
    We keep these fields OUT of Business to avoid churn and keep models stable.
    """

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="stripe_connect")

    charges_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)

    details_submitted = models.BooleanField(default=False)
    requirements_due = models.JSONField(default=dict, blank=True)

    last_checked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"StripeConnectProfile(business_id={self.business_id}, completed={self.onboarding_completed})"
