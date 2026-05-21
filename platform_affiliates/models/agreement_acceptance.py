from __future__ import annotations

from django.conf import settings
from django.db import models


class AffiliateAgreementAcceptance(models.Model):
    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="agreement_acceptances",
        on_delete=models.CASCADE,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="affiliate_agreement_acceptances",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    agreement_version = models.CharField(max_length=64)
    agreement_title = models.CharField(max_length=180)
    agreement_body_snapshot = models.TextField()

    accepted_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-accepted_at"]
        indexes = [
            models.Index(fields=["affiliate", "accepted_at"]),
            models.Index(fields=["agreement_version"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate_id} accepted {self.agreement_version}"