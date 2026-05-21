from __future__ import annotations

from django.conf import settings
from django.db import models

from platform_affiliates.choices import AffiliateStatus, PayoutProvider
from platform_affiliates.constants import DEFAULT_AFFILIATE_COMMISSION_RATE_BPS


class AffiliatePartner(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="affiliate_partner",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    name = models.CharField(max_length=180)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, default="")

    address_line_1 = models.CharField(max_length=220, blank=True, default="")
    address_line_2 = models.CharField(max_length=220, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=2, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    code = models.CharField(max_length=32, unique=True)

    status = models.CharField(
        max_length=20,
        choices=AffiliateStatus.choices,
        default=AffiliateStatus.PENDING,
    )

    commission_rate_bps = models.PositiveIntegerField(
        default=DEFAULT_AFFILIATE_COMMISSION_RATE_BPS,
        help_text="1000 bps = 10% of net SyncWorks revenue.",
    )

    payout_provider = models.CharField(
        max_length=20,
        choices=PayoutProvider.choices,
        default=PayoutProvider.MANUAL,
    )
    payout_email = models.EmailField(blank=True, default="")
    payout_notes = models.TextField(blank=True, default="")
    external_payout_reference = models.CharField(max_length=255, blank=True, default="")

    application_notes = models.TextField(blank=True, default="")
    referral_strategy = models.TextField(blank=True, default="")

    agreement_version = models.CharField(max_length=64, blank=True, default="")
    agreement_accepted_at = models.DateTimeField(null=True, blank=True)
    agreement_accepted_ip = models.GenericIPAddressField(null=True, blank=True)
    agreement_accepted_user_agent = models.TextField(blank=True, default="")

    notes = models.TextField(blank=True, default="")

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="approved_affiliates",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["status"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"