from __future__ import annotations

from datetime import date
from django.conf import settings
from django.db import models
from django.utils import timezone


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timezone.timedelta(days=1)


class UserBillingProfile(models.Model):
    """
    USER-level billing/profile access record.

    Used for:
      - Stripe customer + card snapshot
      - user-first subscriptions
      - private beta/business access before a business exists
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_billing_profile",
    )

    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_default_payment_method_id = models.CharField(max_length=128, blank=True, default="")
    stripe_setup_complete = models.BooleanField(default=False)

    # User-first subscription snapshot
    stripe_subscription_id = models.CharField(max_length=128, blank=True, default="")
    subscription_status = models.CharField(max_length=32, blank=True, default="")
    subscription_current_period_end = models.DateTimeField(null=True, blank=True)
    subscription_cancel_at_period_end = models.BooleanField(default=False)

    # Card snapshot for UI / expiry display
    card_brand = models.CharField(max_length=32, blank=True, default="")
    card_last4 = models.CharField(max_length=8, blank=True, default="")
    card_exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    card_exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    card_updated_at = models.DateTimeField(null=True, blank=True)

    # ✅ Private access / beta unlock (USER-LEVEL)
    beta_access_granted = models.BooleanField(default=False)
    beta_access_granted_at = models.DateTimeField(null=True, blank=True)
    beta_access_code = models.CharField(max_length=64, blank=True, default="")
    beta_billing_exempt = models.BooleanField(default=False)
    beta_subscriptions_waived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def update_card_snapshot(
        self,
        *,
        brand: str = "",
        last4: str = "",
        exp_month: int | None = None,
        exp_year: int | None = None,
    ) -> None:
        self.card_brand = (brand or "")[:32]
        self.card_last4 = (last4 or "")[:8]
        self.card_exp_month = exp_month
        self.card_exp_year = exp_year
        self.card_updated_at = timezone.now()

    def card_expiry_date(self) -> date | None:
        if not self.card_exp_year or not self.card_exp_month:
            return None
        try:
            return _last_day_of_month(int(self.card_exp_year), int(self.card_exp_month))
        except Exception:
            return None

    def days_to_card_expiry(self) -> int | None:
        exp = self.card_expiry_date()
        if not exp:
            return None
        return (exp - timezone.localdate()).days

    def is_card_expired(self) -> bool:
        d = self.days_to_card_expiry()
        return d is not None and d < 0

    def grant_beta_access(
        self,
        *,
        code: str,
        billing_exempt: bool = False,
        subscriptions_waived: bool = True,
    ) -> None:
        self.beta_access_granted = True
        self.beta_access_granted_at = timezone.now()
        self.beta_access_code = (code or "").strip()[:64]
        self.beta_billing_exempt = bool(billing_exempt)
        self.beta_subscriptions_waived = bool(subscriptions_waived)