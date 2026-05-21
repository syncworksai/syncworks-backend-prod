from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from platform_affiliates.choices import AttributionSource


class ReferralAttribution(models.Model):
    business = models.OneToOneField(
        "user_accounts.Business",
        related_name="affiliate_attribution",
        on_delete=models.CASCADE,
    )

    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="attributions",
        on_delete=models.PROTECT,
    )

    referral_code = models.CharField(max_length=32)

    attribution_source = models.CharField(
        max_length=30,
        choices=AttributionSource.choices,
        default=AttributionSource.LINK,
    )

    locked_at = models.DateTimeField(default=timezone.now)

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="assigned_affiliate_attributions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    admin_note = models.TextField(blank=True, default="")
    effective_from = models.DateField(default=timezone.localdate)
    retroactive = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["referral_code"]),
            models.Index(fields=["affiliate", "created_at"]),
            models.Index(fields=["effective_from"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_id} -> {self.affiliate_id} ({self.referral_code})"