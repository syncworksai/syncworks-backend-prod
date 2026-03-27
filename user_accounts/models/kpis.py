from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.db.models import Count, Sum
from django.utils import timezone

from user_accounts.models.user import User
from user_accounts.models.business import Business
from user_accounts.models.tickets import Ticket, TicketMessage
from user_accounts.models.billing import Invoice


class PlatformDailyKpi(models.Model):
    day = models.DateField(unique=True)

    users_total = models.PositiveIntegerField(default=0)
    businesses_total = models.PositiveIntegerField(default=0)
    tickets_total = models.PositiveIntegerField(default=0)
    tickets_new = models.PositiveIntegerField(default=0)
    tickets_completed = models.PositiveIntegerField(default=0)
    tickets_paid = models.PositiveIntegerField(default=0)

    invoices_paid_count = models.PositiveIntegerField(default=0)
    gmv_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    platform_fees_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    avg_response_time_seconds = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-day"]

    def __str__(self) -> str:
        return f"Platform KPI {self.day}"


class BusinessDailyKpi(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="daily_kpis",
    )
    day = models.DateField()

    tickets_total = models.PositiveIntegerField(default=0)
    tickets_completed = models.PositiveIntegerField(default=0)
    tickets_paid = models.PositiveIntegerField(default=0)

    invoices_paid_count = models.PositiveIntegerField(default=0)
    gmv_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    platform_fees_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("business", "day")]
        ordering = ["-day", "business_id"]

    def __str__(self) -> str:
        return f"Business KPI {self.business_id} {self.day}"


class MarketplaceCellDailyKpi(models.Model):
    day = models.DateField()
    zip_code = models.CharField(max_length=10, blank=True, default="")
    category_key = models.CharField(max_length=255, blank=True, default="")

    tickets_created = models.PositiveIntegerField(default=0)
    tickets_viewed = models.PositiveIntegerField(default=0)
    tickets_declined = models.PositiveIntegerField(default=0)
    tickets_assigned = models.PositiveIntegerField(default=0)
    tickets_completed = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("day", "zip_code", "category_key")]
        ordering = ["-day", "zip_code", "category_key"]

    def __str__(self) -> str:
        return f"Marketplace KPI {self.day} {self.zip_code} {self.category_key}"


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