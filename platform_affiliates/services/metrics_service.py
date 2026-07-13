from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from platform_affiliates.choices import CommissionStatus, RevenueSource
from platform_affiliates.models import AffiliateCommissionLedger, AffiliatePartner, ReferralAttribution


def _decimal(value) -> Decimal:
    return Decimal(str(value or "0.00"))


def _month_range():
    today = timezone.localdate()
    start = today.replace(day=1)
    return start, today


HEALTH_REVENUE_SOURCES = [
    RevenueSource.HEALTH_SUBSCRIPTION,
    RevenueSource.HEALTH_AI_SUBSCRIPTION,
]


def get_godmode_overview_metrics() -> dict:
    month_start, today = _month_range()

    monthly_commissions = AffiliateCommissionLedger.objects.filter(
        source_date__gte=month_start,
        source_date__lte=today,
    )

    health_commissions = monthly_commissions.filter(
        revenue_source__in=HEALTH_REVENUE_SOURCES,
    )

    return {
        "total_affiliates": AffiliatePartner.objects.count(),
        "pending_affiliates": AffiliatePartner.objects.filter(status="PENDING").count(),
        "active_affiliates": AffiliatePartner.objects.filter(status="ACTIVE").count(),
        "referred_businesses": ReferralAttribution.objects.count(),
        "active_referred_businesses": ReferralAttribution.objects.filter(business__is_active=True).count(),
        "referred_users": sum(
            affiliate.referred_users.count()
            for affiliate in AffiliatePartner.objects.all()
        ),
        "monthly_health_revenue": _decimal(
            health_commissions.aggregate(total=Sum("net_syncworks_revenue_amount"))["total"]
        ),
        "monthly_syncworks_revenue": _decimal(
            monthly_commissions.aggregate(total=Sum("net_syncworks_revenue_amount"))["total"]
        ),
        "monthly_commissions_owed": _decimal(
            monthly_commissions.filter(status__in=[CommissionStatus.PENDING, CommissionStatus.APPROVED])
            .aggregate(total=Sum("commission_amount"))["total"]
        ),
        "lifetime_commissions_paid": _decimal(
            AffiliateCommissionLedger.objects.filter(status=CommissionStatus.PAID)
            .aggregate(total=Sum("commission_amount"))["total"]
        ),
    }


def get_affiliate_dashboard_metrics(affiliate: AffiliatePartner) -> dict:
    month_start, today = _month_range()

    ledger = AffiliateCommissionLedger.objects.filter(affiliate=affiliate)
    monthly_ledger = ledger.filter(source_date__gte=month_start, source_date__lte=today)
    monthly_health_ledger = monthly_ledger.filter(revenue_source__in=HEALTH_REVENUE_SOURCES)

    return {
        "referred_businesses": ReferralAttribution.objects.filter(affiliate=affiliate).count(),
        "active_referred_businesses": ReferralAttribution.objects.filter(
            affiliate=affiliate,
            business__is_active=True,
        ).count(),
        "referred_users": affiliate.referred_users.count(),
        "monthly_health_revenue": _decimal(
            monthly_health_ledger.aggregate(total=Sum("net_syncworks_revenue_amount"))["total"]
        ),
        "monthly_syncworks_revenue": _decimal(
            monthly_ledger.aggregate(total=Sum("net_syncworks_revenue_amount"))["total"]
        ),
        "pending_commission": _decimal(
            ledger.filter(status__in=[CommissionStatus.PENDING, CommissionStatus.APPROVED])
            .aggregate(total=Sum("commission_amount"))["total"]
        ),
        "paid_commission": _decimal(
            ledger.filter(status=CommissionStatus.PAID).aggregate(total=Sum("commission_amount"))["total"]
        ),
        "lifetime_commission": _decimal(
            ledger.aggregate(total=Sum("commission_amount"))["total"]
        ),
    }


def affiliate_list_metrics_queryset():
    return AffiliatePartner.objects.annotate(
        referred_business_count=Count("attributions", distinct=True),
        active_business_count=Count(
            "attributions",
            filter=Q(attributions__business__is_active=True),
            distinct=True,
        ),
    ).order_by("-created_at")