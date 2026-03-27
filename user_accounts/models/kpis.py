from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from user_accounts.models import User, Ticket, Business, TicketMessage
from user_accounts.models.billing import Invoice


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except Exception:
        return 0.0


def compute_kpis():
    users_by_role = {
        row["role"] or "UNKNOWN": row["c"]
        for row in User.objects.values("role").annotate(c=Count("id"))
    }

    tickets_by_status = {
        row["status"] or "UNKNOWN": row["c"]
        for row in Ticket.objects.values("status").annotate(c=Count("id"))
    }

    paid_invoices = Invoice.objects.filter(status=Invoice.Status.PAID)

    gmv = paid_invoices.aggregate(s=Sum("total"))["s"] or Decimal("0.00")
    fees = paid_invoices.aggregate(s=Sum("platform_fee_amount"))["s"] or Decimal("0.00")
    paid_invoice_count = paid_invoices.count()

    active_businesses = Business.objects.filter(is_active=True).count()

    avg_seconds = None
    total_seconds = 0
    n = 0

    for t in Ticket.objects.all().only("id", "customer_id", "created_at"):
        first_provider = (
            TicketMessage.objects
            .filter(ticket_id=t.id)
            .exclude(sender_id=t.customer_id)
            .order_by("created_at")
            .first()
        )
        if first_provider:
            delta = first_provider.created_at - t.created_at
            total_seconds += max(int(delta.total_seconds()), 0)
            n += 1

    if n:
        avg_seconds = total_seconds / n

    now = timezone.now()

    def per_day(days: int):
        start = now - timedelta(days=days)
        qs = Ticket.objects.filter(created_at__gte=start).only("created_at")

        buckets = {}
        for t in qs:
            d = t.created_at.date().isoformat()
            buckets[d] = buckets.get(d, 0) + 1
        return buckets

    paid_ticket_count = Ticket.objects.filter(status=Ticket.Status.PAID).count()
    invoiced_ticket_count = Ticket.objects.filter(status=Ticket.Status.INVOICED).count()
    completed_ticket_count = Ticket.objects.filter(status=Ticket.Status.COMPLETED).count()

    return {
        "users_by_role": users_by_role,
        "tickets_by_status": tickets_by_status,
        "gmv_paid": _to_float(gmv),
        "platform_fees_paid": _to_float(fees),
        "paid_invoice_count": paid_invoice_count,
        "paid_ticket_count": paid_ticket_count,
        "invoiced_ticket_count": invoiced_ticket_count,
        "completed_ticket_count": completed_ticket_count,
        "active_businesses": active_businesses,
        "avg_response_time_seconds": avg_seconds,
        "tickets_created_last_7_days": per_day(7),
        "tickets_created_last_30_days": per_day(30),
    }