from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserBillingProfile(models.Model):
    """
    USER-level billing profile.
    - Exists for every user even before they create/upgrade to a Business.
    - Stores card-on-file snapshot + Stripe customer + default payment method.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_billing_profile",
    )

    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_default_payment_method_id = models.CharField(max_length=128, blank=True, default="")
    stripe_setup_complete = models.BooleanField(default=False)

    # Card snapshot for UI / expiry display
    card_brand = models.CharField(max_length=32, blank=True, default="")
    card_last4 = models.CharField(max_length=8, blank=True, default="")
    card_exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    card_exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    card_updated_at = models.DateTimeField(null=True, blank=True)

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