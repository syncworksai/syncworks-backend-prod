# backend/user_accounts/services/cash_fee_billing.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from user_accounts.models import Business, CashFeeInvoice, Ticket


def month_range_for_previous_month(today: Optional[date] = None) -> Tuple[date, date, str]:
    """
    Returns (start, end, ym) for the previous calendar month.
    ym is YYYY-MM.
    """
    today = today or timezone.localdate()
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = last_prev_month.replace(day=1)
    ym = f"{first_prev_month.year:04d}-{first_prev_month.month:02d}"
    return first_prev_month, last_prev_month, ym


@dataclass
class CashFeeResult:
    businesses_considered: int = 0
    invoices_created: int = 0
    invoices_skipped_zero: int = 0
    invoices_skipped_existing: int = 0
    businesses_skipped_exempt: int = 0


def _business_is_exempt(b: Business) -> bool:
    # Prefer your helper if present
    try:
        return bool(b.is_billing_exempt_now())
    except Exception:
        # Field fallback
        if getattr(b, "billing_exempt", False):
            until = getattr(b, "billing_exempt_until", None)
            if until is None:
                return True
            try:
                return until >= timezone.localdate()
            except Exception:
                return True
        return False


@transaction.atomic
def generate_monthly_cash_fee_invoices(
    *,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    fee_bps: int = 100,   # 1% default
    due_days: int = 7,    # due 7 days from now
) -> CashFeeResult:
    """
    Creates CashFeeInvoice rows for previous month cash-confirmed tickets.

    Ticket inclusion criteria:
      - assigned_business = business
      - payment_method = CASH
      - cash_confirmed_at is set
      - cash_confirmed_at date within [period_start..period_end]
      - sum(total_amount_cents) > 0
    """
    if period_start is None or period_end is None:
        period_start, period_end, ym = month_range_for_previous_month()
    else:
        ym = f"{period_start.year:04d}-{period_start.month:02d}"

    res = CashFeeResult()

    qs = Business.objects.all()
    res.businesses_considered = qs.count()

    for b in qs.iterator():
        if _business_is_exempt(b):
            res.businesses_skipped_exempt += 1
            continue

        # Prevent duplicates (idempotent)
        existing = (
            CashFeeInvoice.objects.filter(
                business=b,
                period_start=period_start,
                period_end=period_end,
            )
            .exclude(status=CashFeeInvoice.Status.VOID)
            .first()
        )
        if existing:
            res.invoices_skipped_existing += 1
            continue

        # Sum GMV for cash-confirmed tickets in that period
        cash_gmv_cents = (
            Ticket.objects.filter(
                assigned_business=b,
                payment_method=Ticket.PaymentMethod.CASH,
                cash_confirmed_at__isnull=False,
                cash_confirmed_at__date__gte=period_start,
                cash_confirmed_at__date__lte=period_end,
            )
            .aggregate(s=Sum("total_amount_cents"))
            .get("s")
            or 0
        )

        cash_gmv_cents = int(cash_gmv_cents or 0)
        if cash_gmv_cents <= 0:
            res.invoices_skipped_zero += 1
            continue

        fee_cents = int(
            (Decimal(cash_gmv_cents) * Decimal(int(fee_bps)) / Decimal("10000")).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        fee_cents = max(0, fee_cents)

        due_date = timezone.localdate() + timedelta(days=max(0, int(due_days)))

        CashFeeInvoice.objects.create(
            business=b,
            status=CashFeeInvoice.Status.OPEN,
            currency="usd",
            amount_cents=fee_cents,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            memo=f"Cash fee {ym} • {fee_bps/100:.2f}% of cash GMV (${cash_gmv_cents/100:.2f})",
            created_by=None,
        )
        res.invoices_created += 1

        # Optional: Mark included month on tickets (only if field exists)
        try:
            Ticket.objects.filter(
                assigned_business=b,
                payment_method=Ticket.PaymentMethod.CASH,
                cash_confirmed_at__isnull=False,
                cash_confirmed_at__date__gte=period_start,
                cash_confirmed_at__date__lte=period_end,
            ).update(cash_fee_invoiced_month=ym)
        except Exception:
            pass

    return res


@transaction.atomic
def mark_overdue_cash_fee_invoices(today: Optional[date] = None) -> int:
    """
    Marks OPEN invoices as OVERDUE if due_date has passed.
    Returns number updated.
    """
    today = today or timezone.localdate()
    qs = CashFeeInvoice.objects.filter(
        status=CashFeeInvoice.Status.OPEN,
        due_date__isnull=False,
        due_date__lt=today,
    )
    return qs.update(status=CashFeeInvoice.Status.OVERDUE)
