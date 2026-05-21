from __future__ import annotations

from decimal import Decimal

from django.db import models

from platform_affiliates.choices import PayoutBatchStatus


class AffiliatePayoutBatch(models.Model):
    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="payout_batches",
        on_delete=models.PROTECT,
    )

    period_start = models.DateField()
    period_end = models.DateField()

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(
        max_length=20,
        choices=PayoutBatchStatus.choices,
        default=PayoutBatchStatus.DRAFT,
    )

    paid_at = models.DateTimeField(null=True, blank=True)
    external_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        indexes = [
            models.Index(fields=["affiliate", "status"]),
            models.Index(fields=["period_start", "period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate_id} {self.period_start} - {self.period_end}: {self.total_amount}"