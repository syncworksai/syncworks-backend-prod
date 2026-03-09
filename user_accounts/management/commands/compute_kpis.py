# user_accounts/management/commands/compute_kpis.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone

from user_accounts.models import (
    Business,
    Ticket,
    Invoice,
    PlatformDailyKpi,
    BusinessDailyKpi,
    MarketplaceCellDailyKpi,
)

User = get_user_model()


def _zip_prefix(z: str) -> str:
    z = (z or "").strip()
    if len(z) >= 3:
        return z[:3]
    return "UNK"


class Command(BaseCommand):
    help = "Compute daily KPI snapshots (platform + business + marketplace cells)."

    def add_arguments(self, parser):
        parser.add_argument("--day", type=str, default="", help="YYYY-MM-DD; defaults to yesterday")
        parser.add_argument("--days", type=int, default=1, help="Compute N days ending at --day (or yesterday).")

    def handle(self, *args, **opts):
        if opts["day"]:
            y, m, d = [int(x) for x in opts["day"].split("-")]
            end = date(y, m, d)
        else:
            end = timezone.localdate() - timedelta(days=1)

        n = max(1, min(int(opts["days"]), 60))
        days = [end - timedelta(days=i) for i in range(n)]
        days.reverse()

        for day in days:
            self.stdout.write(self.style.WARNING(f"Computing KPIs for {day}..."))
            self.compute_day(day)

        self.stdout.write(self.style.SUCCESS("Done."))

    def compute_day(self, day: date):
        start_dt = timezone.make_aware(timezone.datetime(day.year, day.month, day.day, 0, 0, 0))
        end_dt = start_dt + timedelta(days=1)

        # -------- Platform snapshot --------
        signups = User.objects.filter(date_joined__gte=start_dt, date_joined__lt=end_dt).count()
        businesses_created = Business.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt).count()

        active_businesses_30d = Business.objects.filter(
            is_active=True,
            created_at__gte=timezone.now() - timedelta(days=30),
        ).count()

        tickets_created = Ticket.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt).count()
        tickets_completed = Ticket.objects.filter(completed_at__gte=start_dt, completed_at__lt=end_dt).count()
        tickets_cancelled = Ticket.objects.filter(cancelled_at__gte=start_dt, cancelled_at__lt=end_dt).count()

        open_backlog = Ticket.objects.filter(
            status__in=["NEW", "ASSIGNED", "ACCEPTED", "IN_PROGRESS"]
        ).count()

        marketplace_tickets_created = Ticket.objects.filter(
            is_marketplace=True,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        ).count()

        marketplace_tickets_accepted = Ticket.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
            is_marketplace=True,
            accepted_at__isnull=False,
        ).count()

        fill_rate = Decimal("0.0")
        if marketplace_tickets_created > 0:
            fill_rate = Decimal(marketplace_tickets_accepted) / Decimal(marketplace_tickets_created)

        inv_day = Invoice.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt).exclude(status="VOID")

        gmv = inv_day.aggregate(s=Sum("total"))["s"] or Decimal("0.00")
        cash_gmv = inv_day.filter(payment_method="CASH").aggregate(s=Sum("total"))["s"] or Decimal("0.00")

        platform_fee_collected = inv_day.filter(platform_fee_collected=True).aggregate(s=Sum("platform_fee_amount"))["s"] or Decimal("0.00")
        platform_fee_due = inv_day.filter(platform_fee_collected=False).aggregate(s=Sum("platform_fee_amount"))["s"] or Decimal("0.00")

        PlatformDailyKpi.objects.update_or_create(
            day=day,
            defaults=dict(
                signups=signups,
                businesses_created=businesses_created,
                active_businesses_30d=active_businesses_30d,
                marketplace_tickets_created=marketplace_tickets_created,
                marketplace_tickets_accepted=marketplace_tickets_accepted,
                marketplace_fill_rate=fill_rate,
                tickets_created=tickets_created,
                tickets_completed=tickets_completed,
                tickets_cancelled=tickets_cancelled,
                open_backlog=open_backlog,
                gmv=gmv,
                cash_gmv=cash_gmv,
                platform_fee_collected=platform_fee_collected,
                platform_fee_due=platform_fee_due,
            ),
        )

        # -------- Business snapshots --------
        # Use Ticket.assigned_business_id and Invoice.ticket relation
        biz_ids = list(Business.objects.filter(is_active=True).values_list("id", flat=True))

        for bid in biz_ids:
            t_qs = Ticket.objects.filter(assigned_business_id=bid)

            created = t_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt).count()
            assigned = t_qs.filter(status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "CLOSED"]).filter(
                created_at__gte=start_dt, created_at__lt=end_dt
            ).count()

            accepted = t_qs.filter(accepted_at__gte=start_dt, accepted_at__lt=end_dt).count()
            completed = t_qs.filter(completed_at__gte=start_dt, completed_at__lt=end_dt).count()
            cancelled = t_qs.filter(cancelled_at__gte=start_dt, cancelled_at__lt=end_dt).count()

            backlog = t_qs.filter(status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS"]).count()

            inv_biz = Invoice.objects.filter(ticket__assigned_business_id=bid, created_at__gte=start_dt, created_at__lt=end_dt).exclude(status="VOID")

            biz_gmv = inv_biz.aggregate(s=Sum("total"))["s"] or Decimal("0.00")
            biz_cash_gmv = inv_biz.filter(payment_method="CASH").aggregate(s=Sum("total"))["s"] or Decimal("0.00")

            biz_fee_collected = inv_biz.filter(platform_fee_collected=True).aggregate(s=Sum("platform_fee_amount"))["s"] or Decimal("0.00")
            biz_fee_due = inv_biz.filter(platform_fee_collected=False).aggregate(s=Sum("platform_fee_amount"))["s"] or Decimal("0.00")

            BusinessDailyKpi.objects.update_or_create(
                day=day,
                business_id=bid,
                defaults=dict(
                    tickets_created=created,
                    tickets_assigned=assigned,
                    tickets_accepted=accepted,
                    tickets_completed=completed,
                    tickets_cancelled=cancelled,
                    open_backlog=backlog,
                    gmv=biz_gmv,
                    cash_gmv=biz_cash_gmv,
                    platform_fee_collected=biz_fee_collected,
                    platform_fee_due=biz_fee_due,
                ),
            )

        # -------- Marketplace cells (category, zip_prefix) --------
        # Based on Ticket.service_zip (or SR zip fallback already mirrored into Ticket in your code)
        cells = (
            Ticket.objects.filter(is_marketplace=True, created_at__gte=start_dt, created_at__lt=end_dt)
            .values("category_id", "service_zip")
            .annotate(created=Count("id"), accepted=Count("id", filter=Q(accepted_at__isnull=False)))
        )

        for row in cells:
            cid = row["category_id"] or 0
            zp = _zip_prefix(row["service_zip"] or "")
            created_c = int(row["created"] or 0)
            accepted_c = int(row["accepted"] or 0)
            fr = Decimal("0.0")
            if created_c > 0:
                fr = Decimal(accepted_c) / Decimal(created_c)

            MarketplaceCellDailyKpi.objects.update_or_create(
                day=day,
                category_id=cid,
                zip_prefix=zp,
                defaults=dict(
                    tickets_created=created_c,
                    tickets_accepted=accepted_c,
                    fill_rate=fr,
                ),
            )
