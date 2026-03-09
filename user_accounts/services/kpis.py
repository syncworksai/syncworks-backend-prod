from datetime import timedelta
from django.db.models import Count, Sum
from django.utils import timezone
from user_accounts.models import User, Ticket, Invoice, Business, TicketMessage


def compute_kpis():
    users_by_role = dict(User.objects.values_list("role").annotate(c=Count("id")))
    tickets_by_status = dict(Ticket.objects.values_list("status").annotate(c=Count("id")))

    gmv = Invoice.objects.filter(status=Invoice.Status.PAID).aggregate(s=Sum("amount"))["s"] or 0
    fees = Invoice.objects.filter(status=Invoice.Status.PAID).aggregate(s=Sum("platform_fee"))["s"] or 0
    active_businesses = Business.objects.filter(is_active=True).count()

    # Avg response time: first provider-side message vs ticket created
    # provider-side message = sender != customer and message type != INTERNAL restriction doesn't matter
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
        qs = Ticket.objects.filter(created_at__gte=start)
        # buckets by date
        buckets = {}
        for t in qs.only("created_at"):
            d = t.created_at.date().isoformat()
            buckets[d] = buckets.get(d, 0) + 1
        return buckets

    return {
        "users_by_role": users_by_role,
        "tickets_by_status": tickets_by_status,
        "gmv_paid": float(gmv),
        "platform_fees_paid": float(fees),
        "active_businesses": active_businesses,
        "avg_response_time_seconds": avg_seconds,
        "tickets_created_last_7_days": per_day(7),
        "tickets_created_last_30_days": per_day(30),
    }

