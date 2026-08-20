from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from platform_affiliates.choices import AttributionSource


class PersonalReferralAttribution(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_affiliate_attribution",
    )
    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        on_delete=models.PROTECT,
        related_name="personal_attributions",
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
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="assigned_personal_affiliate_attributions",
    )
    admin_note = models.TextField(blank=True, default="")
    effective_from = models.DateField(default=timezone.localdate)
    retroactive = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"user {self.user_id} -> {self.affiliate_id}"
