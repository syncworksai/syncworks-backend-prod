from __future__ import annotations

from decimal import Decimal

from django.db import models

from platform_affiliates.choices import CommissionStatus, RevenueSource


class AffiliateCommissionLedger(models.Model):
    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="commission_ledger",
        on_delete=models.PROTECT,
    )

    business = models.ForeignKey(
        "user_accounts.Business",
        related_name="affiliate_commissions",
        on_delete=models.PROTECT,
    )

    attribution = models.ForeignKey(
        "platform_affiliates.ReferralAttribution",
        related_name="commission_ledger",
        on_delete=models.PROTECT,
    )

    revenue_source = models.CharField(
        max_length=40,
        choices=RevenueSource.choices,
        default=RevenueSource.PLATFORM_FEE,
    )

    gross_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_syncworks_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate_bps = models.PositiveIntegerField()
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=20,
        choices=CommissionStatus.choices,
        default=CommissionStatus.PENDING,
    )

    source_reference = models.CharField(
        max_length=255,
        help_text="Unique reference from invoice, subscription, webhook, or manual source.",
    )
    source_date = models.DateField()

    payout_batch = models.ForeignKey(
        "platform_affiliates.AffiliatePayoutBatch",
        related_name="commission_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    memo = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-source_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["revenue_source", "source_reference"],
                name="unique_affiliate_commission_source_reference",
            )
        ]
        indexes = [
            models.Index(fields=["affiliate", "status"]),
            models.Index(fields=["business", "source_date"]),
            models.Index(fields=["revenue_source"]),
            models.Index(fields=["source_reference"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate_id} {self.revenue_source} {self.commission_amount}"