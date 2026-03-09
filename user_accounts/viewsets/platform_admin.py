# backend/user_accounts/viewsets/platform_admin.py
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.business import Business
from user_accounts.models.tickets import Ticket
from user_accounts.models.billing import Invoice
from user_accounts.models.platform_billing import PlatformBillingProfile, PlatformPricing
from user_accounts.services.god_mode import is_god_mode


class PlatformKPIAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_god_mode(request.user):
            return Response({"detail": "Not allowed."}, status=403)

        today = timezone.localdate()
        d7 = today - timedelta(days=6)
        d30 = today - timedelta(days=29)
        mtd_start = today.replace(day=1)
        ytd_start = today.replace(month=1, day=1)

        # ---- Users / Businesses ----
        User = get_user_model()
        users_total = User.objects.count()
        businesses_total = Business.objects.count()
        tickets_total = Ticket.objects.count()
        invoices_total = Invoice.objects.count()

        # role breakdown (safe if role exists)
        role_counts = {}
        try:
            role_counts = dict(
                User.objects.values("role").annotate(c=Count("id")).values_list("role", "c")
            )
        except Exception:
            role_counts = {}

        # signups last 30
        try:
            signups_last_30 = User.objects.filter(date_joined__date__gte=d30, date_joined__date__lte=today).count()
        except Exception:
            signups_last_30 = 0

        # ---- Financials from Invoice ----
        paid = Invoice.objects.filter(status=Invoice.Status.PAID)

        def sum_total(qs):
            return qs.aggregate(v=Coalesce(Sum("total"), Decimal("0.00")))["v"]

        def sum_fee_collected(qs):
            return qs.filter(platform_fee_collected=True).aggregate(v=Coalesce(Sum("platform_fee_amount"), Decimal("0.00")))["v"]

        def sum_fee_due(qs):
            return qs.filter(platform_fee_collected=False).aggregate(v=Coalesce(Sum("platform_fee_amount"), Decimal("0.00")))["v"]

        gmv_lifetime = sum_total(paid)
        gmv_today = sum_total(paid.filter(paid_at__date=today))
        gmv_7d = sum_total(paid.filter(paid_at__date__gte=d7, paid_at__date__lte=today))
        gmv_30d = sum_total(paid.filter(paid_at__date__gte=d30, paid_at__date__lte=today))
        gmv_mtd = sum_total(paid.filter(paid_at__date__gte=mtd_start, paid_at__date__lte=today))
        gmv_ytd = sum_total(paid.filter(paid_at__date__gte=ytd_start, paid_at__date__lte=today))

        cash_gmv_30d = sum_total(
            paid.filter(payment_method=Invoice.PaymentMethod.CASH, paid_at__date__gte=d30, paid_at__date__lte=today)
        )

        fee_collected_today = sum_fee_collected(paid.filter(paid_at__date=today))
        fee_collected_7d = sum_fee_collected(paid.filter(paid_at__date__gte=d7, paid_at__date__lte=today))
        fee_collected_30d = sum_fee_collected(paid.filter(paid_at__date__gte=d30, paid_at__date__lte=today))
        fee_collected_lifetime = sum_fee_collected(paid)

        fee_due_30d = sum_fee_due(paid.filter(paid_at__date__gte=d30, paid_at__date__lte=today))
        fee_due_lifetime = sum_fee_due(paid)

        # ---- Billing health ----
        profiles = PlatformBillingProfile.objects.select_related("business").all()
        businesses_with_card_on_file = profiles.filter(stripe_setup_complete=True).count()
        businesses_locked = profiles.filter(is_locked=True).count()

        # card expiry buckets
        expiring_30 = expiring_15 = expiring_7 = expiring_1 = expired = 0
        for p in profiles:
            d = p.days_to_card_expiry()
            if d is None:
                continue
            if d < 0:
                expired += 1
            elif d <= 1:
                expiring_1 += 1
            elif d <= 7:
                expiring_7 += 1
            elif d <= 15:
                expiring_15 += 1
            elif d <= 30:
                expiring_30 += 1

        # ---- Subscription MRR estimate ----
        pricing = PlatformPricing()
        active_subs = profiles.filter(subscription_status__in=["active", "trialing"]).count()
        mrr_estimate_cents = int(active_subs * int(pricing.sbo_subscription_cents))

        return Response(
            {
                "users_total": users_total,
                "signups_last_30_days": signups_last_30,
                "role_counts": role_counts,

                "businesses_total": businesses_total,
                "businesses_with_card_on_file": businesses_with_card_on_file,
                "businesses_locked": businesses_locked,

                "tickets_total": tickets_total,
                "invoices_total": invoices_total,

                "gmv_lifetime": str(gmv_lifetime),
                "gmv_today": str(gmv_today),
                "gmv_7d": str(gmv_7d),
                "gmv_30d": str(gmv_30d),
                "gmv_mtd": str(gmv_mtd),
                "gmv_ytd": str(gmv_ytd),
                "cash_gmv_30d": str(cash_gmv_30d),

                "platform_fee_collected_today": str(fee_collected_today),
                "platform_fee_collected_7d": str(fee_collected_7d),
                "platform_fee_collected_30d": str(fee_collected_30d),
                "platform_fee_collected_lifetime": str(fee_collected_lifetime),
                "platform_fee_due_30d": str(fee_due_30d),
                "platform_fee_due_lifetime": str(fee_due_lifetime),

                "active_subscriptions": active_subs,
                "mrr_estimate_cents": mrr_estimate_cents,

                "cards_expiring_30": expiring_30,
                "cards_expiring_15": expiring_15,
                "cards_expiring_7": expiring_7,
                "cards_expiring_1": expiring_1,
                "cards_expired": expired,
            }
        )