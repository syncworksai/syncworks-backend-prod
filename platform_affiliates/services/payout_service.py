from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from platform_affiliates.choices import CommissionStatus, PayoutBatchStatus
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    AffiliatePayoutBatch,
    AffiliatePartner,
)


@transaction.atomic
def create_monthly_payout_batch(
    *,
    affiliate: AffiliatePartner,
    period_start,
    period_end,
    notes: str = "",
) -> AffiliatePayoutBatch:
    if period_end < period_start:
        raise ValidationError({"period_end": "Period end cannot be before period start."})

    eligible = AffiliateCommissionLedger.objects.select_for_update().filter(
        affiliate=affiliate,
        payout_batch__isnull=True,
        source_date__gte=period_start,
        source_date__lte=period_end,
        status__in=[CommissionStatus.PENDING, CommissionStatus.APPROVED],
    )

    total = eligible.aggregate(total=Sum("commission_amount"))["total"] or Decimal("0.00")

    if total <= Decimal("0.00"):
        raise ValidationError({"detail": "No eligible commissions found for this payout period."})

    batch = AffiliatePayoutBatch.objects.create(
        affiliate=affiliate,
        period_start=period_start,
        period_end=period_end,
        total_amount=total,
        status=PayoutBatchStatus.DRAFT,
        notes=notes or "",
    )

    eligible.update(
        payout_batch=batch,
        status=CommissionStatus.APPROVED,
    )

    return batch


@transaction.atomic
def mark_payout_batch_paid(
    *,
    batch: AffiliatePayoutBatch,
    external_reference: str = "",
    notes: str = "",
) -> AffiliatePayoutBatch:
    if batch.status == PayoutBatchStatus.PAID:
        return batch

    batch.status = PayoutBatchStatus.PAID
    batch.paid_at = timezone.now()

    if external_reference:
        batch.external_reference = external_reference

    if notes:
        batch.notes = notes

    batch.save(
        update_fields=[
            "status",
            "paid_at",
            "external_reference",
            "notes",
            "updated_at",
        ]
    )

    AffiliateCommissionLedger.objects.filter(payout_batch=batch).update(
        status=CommissionStatus.PAID
    )

    return batch