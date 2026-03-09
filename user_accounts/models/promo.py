# backend/user_accounts/models/promo.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PromoCode(models.Model):
    """
    God Mode controlled promo codes.

    Use cases:
      - billing_exempt=True: FULL exemption (internal/testing) — skips all platform billing.
      - waive_subscriptions=True: waives ONLY base subscriptions (SBO + PM). Seats + 1% fees still apply.
    """
    code = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)

    # ✅ FULL exemption (rare)
    billing_exempt = models.BooleanField(default=False)

    # ✅ Subscription-only waiver (SWFF26)
    waive_subscriptions = models.BooleanField(default=False)

    expires_at = models.DateTimeField(null=True, blank=True)

    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    redemption_count = models.PositiveIntegerField(default=0)

    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_promo_codes",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.code

    def is_valid_now(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_redemptions is not None and self.redemption_count >= self.max_redemptions:
            return False
        return True


class PromoRedemption(models.Model):
    promo = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promo_redemptions")
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="promo_redemptions")

    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("promo", "business")
        ordering = ("-redeemed_at",)

    def __str__(self) -> str:
        return f"{self.promo.code} -> business #{self.business_id}"