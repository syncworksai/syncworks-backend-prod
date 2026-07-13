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


def _existing_commission(
    *,
    revenue_source: str,
    source_reference: str,
) -> AffiliateCommissionLedger | None:
    return AffiliateCommissionLedger.objects.filter(
        revenue_source=revenue_source,
        source_reference=source_reference,
    ).first()


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

    existing = _existing_commission(
        revenue_source=revenue_source,
        source_reference=source_reference,
    )

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


@transaction.atomic
def record_user_health_subscription_commission(
    *,
    user,
    net_syncworks_revenue_amount,
    source_reference: str,
    source_date=None,
    gross_revenue_amount="0.00",
    memo: str = "",
    health_ai: bool = False,
) -> AffiliateCommissionLedger | None:
    """
    Records commission for a referred Personal/Health user.

    This is intentionally user-based instead of business-based because Health is
    the consumer adoption product. It uses User.referred_by_affiliate, which is
    already populated during registration when an active affiliate code is used.
    """

    source_reference = str(source_reference or "").strip()

    if not source_reference:
        raise ValueError("source_reference is required.")

    revenue_source = (
        RevenueSource.HEALTH_AI_SUBSCRIPTION
        if health_ai
        else RevenueSource.HEALTH_SUBSCRIPTION
    )

    existing = _existing_commission(
        revenue_source=revenue_source,
        source_reference=source_reference,
    )

    if existing:
        return existing

    affiliate = getattr(user, "referred_by_affiliate", None)

    if not affiliate:
        return None

    net_amount = _money(net_syncworks_revenue_amount)
    gross_amount = _money(gross_revenue_amount)

    commission_amount = _calculate_commission(
        net_amount,
        affiliate.commission_rate_bps,
    )

    return AffiliateCommissionLedger.objects.create(
        affiliate=affiliate,
        business=None,
        attribution=None,
        revenue_source=revenue_source,
        gross_revenue_amount=gross_amount,
        net_syncworks_revenue_amount=net_amount,
        commission_rate_bps=affiliate.commission_rate_bps,
        commission_amount=commission_amount,
        source_reference=source_reference,
        source_date=source_date or timezone.localdate(),
        memo=memo or f"Health subscription commission for user {getattr(user, 'id', '')}",
    )