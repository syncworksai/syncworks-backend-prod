from __future__ import annotations

from django.db import models


class ReferralClick(models.Model):
    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="referral_clicks",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    code = models.CharField(max_length=32)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    landing_path = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} @ {self.created_at}"