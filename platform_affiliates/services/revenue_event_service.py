from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from platform_affiliates.choices import AffiliateStatus, CommissionStatus
from platform_affiliates.models import AffiliateCommissionLedger, PersonalReferralAttribution, ReferralAttribution

CENT = Decimal("0.01")
BPS_DIVISOR = Decimal("10000")


def _money(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_commission(net_syncworks_revenue, rate_bps: int) -> Decimal:
    net = _money(net_syncworks_revenue)
    return (net * Decimal(int(rate_bps or 0)) / BPS_DIVISOR).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def record_business_revenue_event(*, business, revenue_source: str, net_syncworks_revenue, gross_transaction_amount=0, source_reference="", memo=""):
    """Create the affiliate commission belonging to a referred Business.

    Business-originated SyncWorks revenue always follows the Business attribution,
    including Marketplace fees, Business subscriptions and platform fees.
    """
    attribution = ReferralAttribution.objects.select_related("affiliate").filter(business=business).first()
    if not attribution or attribution.affiliate.status != AffiliateStatus.ACTIVE:
        return None
    affiliate = attribution.affiliate
    defaults = {
        "business": business,
        "attribution": attribution,
        "gross_revenue_amount": _money(gross_transaction_amount),
        "net_syncworks_revenue_amount": _money(net_syncworks_revenue),
        "commission_rate_bps": affiliate.commission_rate_bps,
        "commission_amount": calculate_commission(net_syncworks_revenue, affiliate.commission_rate_bps),
        "status": CommissionStatus.PENDING,
        "memo": memo,
    }
    if source_reference:
        row, _ = AffiliateCommissionLedger.objects.get_or_create(
            affiliate=affiliate,
            revenue_source=revenue_source,
            source_reference=str(source_reference),
            defaults=defaults,
        )
        return row
    return AffiliateCommissionLedger.objects.create(
        affiliate=affiliate,
        revenue_source=revenue_source,
        source_reference="",
        **defaults,
    )


@transaction.atomic
def record_personal_revenue_event(*, user, revenue_source: str, net_syncworks_revenue, gross_transaction_amount=0, source_reference="", memo=""):
    """Create commission for paid Personal products referred by an affiliate.

    Personal revenue never steals attribution from a referred Business. It is for
    Personal subscriptions/add-ons and other explicitly user-level SyncWorks revenue.
    """
    attribution = PersonalReferralAttribution.objects.select_related("affiliate").filter(user=user).first()
    if not attribution or attribution.affiliate.status != AffiliateStatus.ACTIVE:
        return None
    affiliate = attribution.affiliate
    defaults = {
        "referred_user": user,
        "personal_attribution": attribution,
        "gross_revenue_amount": _money(gross_transaction_amount),
        "net_syncworks_revenue_amount": _money(net_syncworks_revenue),
        "commission_rate_bps": affiliate.commission_rate_bps,
        "commission_amount": calculate_commission(net_syncworks_revenue, affiliate.commission_rate_bps),
        "status": CommissionStatus.PENDING,
        "memo": memo,
    }
    if source_reference:
        row, _ = AffiliateCommissionLedger.objects.get_or_create(
            affiliate=affiliate,
            revenue_source=revenue_source,
            source_reference=str(source_reference),
            defaults=defaults,
        )
        return row
    return AffiliateCommissionLedger.objects.create(
        affiliate=affiliate,
        revenue_source=revenue_source,
        source_reference="",
        **defaults,
    )
