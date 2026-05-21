from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from platform_affiliates.choices import RevenueSource
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    ReferralAttribution,
)


MONEY_QUANT = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value or "0.00")).quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )


def _calculate_commission(
    net_syncworks_revenue_amount: Decimal,
    commission_rate_bps: int,
) -> Decimal:
    return (
        net_syncworks_revenue_amount
        * Decimal(commission_rate_bps)
        / Decimal("10000")
    ).quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )


@transaction.atomic
def record_syncworks_revenue_commission(
    *,
    business,
    net_syncworks_revenue_amount,
    source_reference: str,
    revenue_source: str = RevenueSource.PLATFORM_FEE,
    source_date=None,
    gross_revenue_amount="0.00",
    memo: str = "",
) -> AffiliateCommissionLedger | None:
    source_reference = str(source_reference or "").strip()

    if not source_reference:
        raise ValueError("source_reference is required.")

    existing = AffiliateCommissionLedger.objects.filter(
        revenue_source=revenue_source,
        source_reference=source_reference,
    ).first()

    if existing:
        return existing

    attribution = (
        ReferralAttribution.objects
        .select_related("affiliate", "business")
        .filter(business=business)
        .first()
    )

    if not attribution:
        return None

    affiliate = attribution.affiliate

    net_amount = _money(net_syncworks_revenue_amount)

    gross_amount = _money(gross_revenue_amount)

    commission_amount = _calculate_commission(
        net_amount,
        affiliate.commission_rate_bps,
    )

    return AffiliateCommissionLedger.objects.create(
        affiliate=affiliate,
        business=business,
        attribution=attribution,
        revenue_source=revenue_source,
        gross_revenue_amount=gross_amount,
        net_syncworks_revenue_amount=net_amount,
        commission_rate_bps=affiliate.commission_rate_bps,
        commission_amount=commission_amount,
        source_reference=source_reference,
        source_date=source_date or timezone.localdate(),
        memo=memo or "",
    )