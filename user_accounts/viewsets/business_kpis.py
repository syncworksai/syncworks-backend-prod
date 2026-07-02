from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Ticket
from user_accounts.viewsets.ticket_conversations import _business_context


COMPLETED_STATUSES = {
    Ticket.Status.COMPLETED,
    Ticket.Status.CLOSED,
    Ticket.Status.INVOICED,
    Ticket.Status.PAID,
}


def _aware_start(day: date):
    return timezone.make_aware(datetime.combine(day, time.min))


def _money(cents):
    return float(Decimal(int(cents or 0)) / Decimal("100"))


def _period_start(today: date, period: str) -> date:
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    if period == "year":
        return today.replace(month=1, day=1)
    return today


def _next_period(start: date, period: str) -> date:
    if period == "day":
        return start + timedelta(days=1)
    if period == "week":
        return start + timedelta(days=7)
    if period == "month":
        return (
            start.replace(year=start.year + 1, month=1, day=1)
            if start.month == 12
            else start.replace(month=start.month + 1, day=1)
        )
    return start.replace(year=start.year + 1, month=1, day=1)


def _elapsed_units(today: date, period: str) -> float:
    if period == "week":
        return float(today.weekday() + 1)
    if period == "month":
        return max(float(today.day) / 7.0, 1.0 / 7.0)
    if period == "year":
        return max(float(today.timetuple().tm_yday) / 30.4375, 1.0 / 30.4375)
    return 1.0


def _current_period(qs, today: date, period: str):
    start = _period_start(today, period)
    end = _next_period(start, period)
    period_qs = qs.filter(
        created_at__gte=_aware_start(start),
        created_at__lt=_aware_start(end),
    )
    count = period_qs.count()
    completed = period_qs.filter(status__in=COMPLETED_STATUSES).count()
    paid = period_qs.filter(status=Ticket.Status.PAID).count()
    revenue_cents = period_qs.aggregate(
        value=Sum("total_amount_cents")
    )["value"] or 0

    divisor = _elapsed_units(today, period)
    average_label = {
        "day": "tickets_per_day",
        "week": "tickets_per_day",
        "month": "tickets_per_week",
        "year": "tickets_per_month",
    }[period]

    return {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "tickets": count,
        "completed": completed,
        "paid": paid,
        "revenue": _money(revenue_cents),
        average_label: round(count / divisor, 2),
    }


def _historical_average(qs, period: str):
    trunc = {
        "day": TruncDay,
        "week": TruncWeek,
        "month": TruncMonth,
        "year": TruncYear,
    }[period]
    buckets = list(
        qs.annotate(bucket=trunc("created_at"))
        .values("bucket")
        .annotate(tickets=Count("id"))
        .order_by("bucket")
    )
    values = [int(row["tickets"] or 0) for row in buckets]
    average = round(sum(values) / len(values), 2) if values else 0.0
    return {
        "periods_with_activity": len(values),
        "average_tickets": average,
        "highest_period": max(values) if values else 0,
        "lowest_active_period": min(values) if values else 0,
    }


def _timeseries(qs, period: str, limit: int):
    trunc = {
        "day": TruncDay,
        "week": TruncWeek,
        "month": TruncMonth,
        "year": TruncYear,
    }[period]
    rows = list(
        qs.annotate(bucket=trunc("created_at"))
        .values("bucket")
        .annotate(
            tickets=Count("id"),
            completed=Count(
                "id",
                filter=Q(
                    status__in=COMPLETED_STATUSES
                ),
            ),
            paid=Count(
                "id",
                filter=Q(
                    status=Ticket.Status.PAID
                ),
            ),
            revenue_cents=Sum("total_amount_cents"),
        )
        .order_by("-bucket")[:limit]
    )
    rows.reverse()
    return [
        {
            "period": row["bucket"].date().isoformat(),
            "tickets": int(row["tickets"] or 0),
            "completed": int(row["completed"] or 0),
            "paid": int(row["paid"] or 0),
            "revenue": _money(row["revenue_cents"]),
        }
        for row in rows
    ]


def _dataset(qs, today: date):
    total = qs.count()
    completed = qs.filter(status__in=COMPLETED_STATUSES).count()
    paid = qs.filter(status=Ticket.Status.PAID).count()
    cancelled = qs.filter(status=Ticket.Status.CANCELLED).count()
    revenue_cents = qs.aggregate(
        value=Sum("total_amount_cents")
    )["value"] or 0

    return {
        "totals": {
            "tickets": total,
            "completed": completed,
            "paid": paid,
            "cancelled": cancelled,
            "open": max(total - completed - cancelled, 0),
            "revenue": _money(revenue_cents),
            "completion_rate": round(
                (completed / total) * 100,
                2,
            ) if total else 0.0,
        },
        "current": {
            "day": _current_period(qs, today, "day"),
            "week": _current_period(qs, today, "week"),
            "month": _current_period(qs, today, "month"),
            "year": _current_period(qs, today, "year"),
        },
        "historical_averages": {
            "daily": _historical_average(qs, "day"),
            "weekly": _historical_average(qs, "week"),
            "monthly": _historical_average(qs, "month"),
            "yearly": _historical_average(qs, "year"),
        },
        "timeseries": {
            "daily": _timeseries(qs, "day", 30),
            "weekly": _timeseries(qs, "week", 12),
            "monthly": _timeseries(qs, "month", 12),
            "yearly": _timeseries(qs, "year", 5),
        },
    }


class BusinessKpiViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        business, _, _ = _business_context(request)
        today = timezone.localdate()

        all_history = Ticket.objects.filter(
            assigned_business=business,
        )
        syncworks_only = all_history.filter(
            is_imported=False,
            exclude_from_operational_kpis=False,
        )
        imported_history = all_history.filter(is_imported=True)

        return Response(
            {
                "business": {
                    "id": business.id,
                    "name": business.name,
                },
                "generated_at": timezone.now().isoformat(),
                "definitions": {
                    "all_history": (
                        "All business tickets, including migrated records."
                    ),
                    "syncworks_only": (
                        "Tickets created natively in SyncWorks. "
                        "Imported history is excluded."
                    ),
                    "imported_history": (
                        "Historical tickets migrated from another system."
                    ),
                    "week_start": "Monday",
                    "averages": (
                        "Historical averages use periods that contain activity. "
                        "Current period run rates use elapsed calendar time."
                    ),
                },
                "all_history": _dataset(all_history, today),
                "syncworks_only": _dataset(syncworks_only, today),
                "imported_history": {
                    "tickets": imported_history.count(),
                    "revenue": _money(
                        imported_history.aggregate(
                            value=Sum("total_amount_cents")
                        )["value"] or 0
                    ),
                    "source_systems": list(
                        imported_history.exclude(source_system="")
                        .values("source_system")
                        .annotate(tickets=Count("id"))
                        .order_by("-tickets", "source_system")
                    ),
                },
            }
        )
