# backend/user_accounts/services/god_mode_metrics.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.core.cache import cache


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _to_date(x: Optional[str]) -> Optional[date]:
    if not x:
        return None
    try:
        return datetime.strptime(str(x).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def resolve_range(*, start: Optional[str], end: Optional[str], days: Optional[str], default_days: int = 30) -> Tuple[date, date]:
    """
    Resolve a date range inclusive of start/end for reporting.
    Accepts:
      - ?start=YYYY-MM-DD&end=YYYY-MM-DD
      - ?days=30  (ending today)
    Returns: (start_date, end_date)
    """
    today = timezone.localdate()

    start_d = _to_date(start)
    end_d = _to_date(end)

    if start_d and end_d:
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        return start_d, end_d

    if start_d and not end_d:
        return start_d, today

    if end_d and not start_d:
        # default window ending at end_d
        try:
            d = int(days or default_days)
        except Exception:
            d = default_days
        d = max(1, min(d, 3650))
        return end_d - timedelta(days=d - 1), end_d

    # days mode
    try:
        d = int(days or default_days)
    except Exception:
        d = default_days
    d = max(1, min(d, 3650))
    return today - timedelta(days=d - 1), today


def _money(cents: Optional[int]) -> int:
    try:
        return int(cents or 0)
    except Exception:
        return 0


def _safe_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def _biz_locked_q(biz_model) -> Q:
    """
    Support different schemas:
      - is_locked boolean
      - locked_at datetime
      - billing_locked boolean
    """
    fields = {f.name for f in biz_model._meta.get_fields() if hasattr(f, "name")}
    if "is_locked" in fields:
        return Q(is_locked=True)
    if "billing_locked" in fields:
        return Q(billing_locked=True)
    if "locked_at" in fields:
        return Q(locked_at__isnull=False)
    # fallback: none locked
    return Q(pk__in=[])


def _biz_card_on_file_q(biz_model) -> Q:
    """
    Support different schemas:
      - stripe_payment_method_id
      - stripe_default_payment_method_id
      - has_card_on_file
      - card_last4 (etc)
    """
    fields = {f.name for f in biz_model._meta.get_fields() if hasattr(f, "name")}
    if "has_card_on_file" in fields:
        return Q(has_card_on_file=True)
    if "stripe_payment_method_id" in fields:
        return ~Q(stripe_payment_method_id__isnull=True) & ~Q(stripe_payment_method_id__exact="")
    if "stripe_default_payment_method_id" in fields:
        return ~Q(stripe_default_payment_method_id__isnull=True) & ~Q(stripe_default_payment_method_id__exact="")
    if "card_last4" in fields:
        return ~Q(card_last4__isnull=True) & ~Q(card_last4__exact="")
    return Q(pk__in=[])


def _ticket_business_fk_fields(ticket_model) -> List[str]:
    """
    Your Ticket error shows:
      - assigned_business_id
      - payer_business_id

    We NEVER reference Ticket.business_id.
    """
    fields = {f.name for f in ticket_model._meta.get_fields() if hasattr(f, "name")}
    candidates = []
    if "assigned_business_id" in fields:
        candidates.append("assigned_business_id")
    if "payer_business_id" in fields:
        candidates.append("payer_business_id")
    return candidates


# -----------------------------------------------------------------------------
# Summary (cached)
# -----------------------------------------------------------------------------
CACHE_KEY_PREFIX = "sw:gmode:summary:"


def cached_summary(start_d: date, end_d: date) -> Dict[str, Any]:
    """
    Cached summary payload used by:
      GET /api/v1/platform/metrics/summary/?days=30
    """
    key = f"{CACHE_KEY_PREFIX}{start_d.isoformat()}:{end_d.isoformat()}"
    cached = cache.get(key)
    if cached:
        return cached

    data = _build_summary(start_d, end_d)
    cache.set(key, data, 60)  # 60s cache is plenty for admin dashboard
    return data


def _build_summary(start_d: date, end_d: date) -> Dict[str, Any]:
    User = get_user_model()

    Business = _safe_model("user_accounts", "Business")
    Ticket = _safe_model("user_accounts", "Ticket")
    Invoice = _safe_model("user_accounts", "Invoice")  # if you have one; otherwise handled safely

    start_dt = timezone.make_aware(datetime.combine(start_d, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(end_d, datetime.max.time()))

    # -------------------------
    # Users
    # -------------------------
    users_total = User.objects.count()

    signups_last_30_days = User.objects.filter(date_joined__gte=timezone.now() - timedelta(days=30)).count()

    # role mix best-effort
    role_counts: Dict[str, int] = {}
    try:
        # common patterns: user.role or user.user_type
        role_field = None
        user_fields = {f.name for f in User._meta.get_fields() if hasattr(f, "name")}
        if "role" in user_fields:
            role_field = "role"
        elif "user_type" in user_fields:
            role_field = "user_type"

        if role_field:
            rows = User.objects.values(role_field).annotate(c=Count("id")).order_by()
            for r in rows:
                k = str(r.get(role_field) or "UNKNOWN").upper()
                role_counts[k] = int(r.get("c") or 0)
    except Exception:
        role_counts = {}

    # -------------------------
    # Businesses
    # -------------------------
    businesses_total = 0
    businesses_locked = 0
    businesses_with_card_on_file = 0
    cards_expired = 0
    cards_expiring_30 = 0
    cards_expiring_7 = 0

    if Business is not None:
        businesses_total = Business.objects.count()
        try:
            businesses_locked = Business.objects.filter(_biz_locked_q(Business)).count()
        except Exception:
            businesses_locked = 0

        try:
            businesses_with_card_on_file = Business.objects.filter(_biz_card_on_file_q(Business)).count()
        except Exception:
            businesses_with_card_on_file = 0

        # card expiry best-effort: if model has card_exp_month/card_exp_year
        try:
            fields = {f.name for f in Business._meta.get_fields() if hasattr(f, "name")}
            if "card_exp_month" in fields and "card_exp_year" in fields:
                today = timezone.localdate()
                # expired if exp date < current month
                y = today.year
                m = today.month
                cards_expired = Business.objects.filter(
                    Q(card_exp_year__lt=y) | (Q(card_exp_year=y) & Q(card_exp_month__lt=m))
                ).count()

                # expiring in 30/7 days (approx by month boundary; simple + good enough)
                in_30 = today + timedelta(days=30)
                in_7 = today + timedelta(days=7)
                cards_expiring_30 = Business.objects.filter(
                    Q(card_exp_year=in_30.year, card_exp_month=in_30.month)
                ).count()
                cards_expiring_7 = Business.objects.filter(
                    Q(card_exp_year=in_7.year, card_exp_month=in_7.month)
                ).count()
        except Exception:
            pass

    # -------------------------
    # Revenue / GMV (best-effort)
    # -------------------------
    # We keep these stable keys so the UI doesn't break, and we can refine later.
    gmv_7d = 0
    gmv_30d = 0
    gmv_mtd = 0
    gmv_ytd = 0
    platform_fee_collected_30d = 0
    platform_fee_due_30d = 0

    # If you have an Invoice model with amount_cents + status/paid_at, sum it.
    if Invoice is not None:
        inv_fields = {f.name for f in Invoice._meta.get_fields() if hasattr(f, "name")}
        amt_field = "amount_cents" if "amount_cents" in inv_fields else ("total_cents" if "total_cents" in inv_fields else None)

        if amt_field:
            now = timezone.now()
            try:
                gmv_7d = _money(
                    Invoice.objects.filter(created_at__gte=now - timedelta(days=7)).aggregate(s=Sum(amt_field)).get("s")
                )
            except Exception:
                gmv_7d = 0

            try:
                gmv_30d = _money(
                    Invoice.objects.filter(created_at__gte=now - timedelta(days=30)).aggregate(s=Sum(amt_field)).get("s")
                )
            except Exception:
                gmv_30d = 0

            # MTD / YTD
            try:
                today = timezone.localdate()
                mtd_start = today.replace(day=1)
                ytd_start = today.replace(month=1, day=1)

                gmv_mtd = _money(
                    Invoice.objects.filter(created_at__gte=timezone.make_aware(datetime.combine(mtd_start, datetime.min.time()))).aggregate(s=Sum(amt_field)).get("s")
                )
                gmv_ytd = _money(
                    Invoice.objects.filter(created_at__gte=timezone.make_aware(datetime.combine(ytd_start, datetime.min.time()))).aggregate(s=Sum(amt_field)).get("s")
                )
            except Exception:
                pass

            # platform fee fields (if present)
            fee_field = None
            if "platform_fee_cents" in inv_fields:
                fee_field = "platform_fee_cents"
            elif "fee_cents" in inv_fields:
                fee_field = "fee_cents"

            if fee_field:
                try:
                    platform_fee_due_30d = _money(
                        Invoice.objects.filter(created_at__gte=now - timedelta(days=30)).aggregate(s=Sum(fee_field)).get("s")
                    )
                except Exception:
                    platform_fee_due_30d = 0

                # collected: if you have paid_at or status=PAID
                try:
                    q_paid = Q()
                    if "paid_at" in inv_fields:
                        q_paid = Q(paid_at__isnull=False)
                    elif "status" in inv_fields:
                        q_paid = Q(status__iexact="PAID")

                    platform_fee_collected_30d = _money(
                        Invoice.objects.filter(created_at__gte=now - timedelta(days=30)).filter(q_paid).aggregate(s=Sum(fee_field)).get("s")
                    )
                except Exception:
                    platform_fee_collected_30d = 0

    # -------------------------
    # Chart Data (daily counts in range)
    # -------------------------
    chart: List[Dict[str, Any]] = []
    try:
        day_count = (end_d - start_d).days + 1
        day_count = max(1, min(day_count, 120))  # keep light

        # Precompute daily signups + business creates (best-effort)
        signups_by_day = {}
        try:
            rows = (
                User.objects.filter(date_joined__gte=start_dt, date_joined__lte=end_dt)
                .extra(select={"day": "date(date_joined)"})
                .values("day")
                .annotate(c=Count("id"))
            )
            for r in rows:
                signups_by_day[str(r["day"])] = int(r["c"])
        except Exception:
            signups_by_day = {}

        biz_by_day = {}
        if Business is not None:
            try:
                # common: created_at
                fields = {f.name for f in Business._meta.get_fields() if hasattr(f, "name")}
                if "created_at" in fields:
                    rows = (
                        Business.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)
                        .extra(select={"day": "date(created_at)"})
                        .values("day")
                        .annotate(c=Count("id"))
                    )
                    for r in rows:
                        biz_by_day[str(r["day"])] = int(r["c"])
            except Exception:
                biz_by_day = {}

        locked_by_day = {}
        if Business is not None:
            try:
                fields = {f.name for f in Business._meta.get_fields() if hasattr(f, "name")}
                if "locked_at" in fields:
                    rows = (
                        Business.objects.filter(locked_at__isnull=False, locked_at__gte=start_dt, locked_at__lte=end_dt)
                        .extra(select={"day": "date(locked_at)"})
                        .values("day")
                        .annotate(c=Count("id"))
                    )
                    for r in rows:
                        locked_by_day[str(r["day"])] = int(r["c"])
            except Exception:
                locked_by_day = {}

        for i in range(day_count):
            d = start_d + timedelta(days=i)
            key = d.isoformat()
            chart.append(
                {
                    "date": key,
                    "dateShort": d.strftime("%m/%d"),
                    "signups": int(signups_by_day.get(key, 0)),
                    "businesses_created": int(biz_by_day.get(key, 0)),
                    "locked_businesses": int(locked_by_day.get(key, 0)),
                }
            )
    except Exception:
        chart = []

    # stable response keys expected by your UI
    return {
        "range": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        "users_total": users_total,
        "signups_last_30_days": signups_last_30_days,
        "role_counts": role_counts,
        "businesses_total": businesses_total,
        "businesses_with_card_on_file": businesses_with_card_on_file,
        "businesses_locked": businesses_locked,
        "cards_expired": cards_expired,
        "cards_expiring_30": cards_expiring_30,
        "cards_expiring_7": cards_expiring_7,
        "gmv_7d": gmv_7d,
        "gmv_30d": gmv_30d,
        "gmv_mtd": gmv_mtd,
        "gmv_ytd": gmv_ytd,
        "platform_fee_collected_30d": platform_fee_collected_30d,
        "platform_fee_due_30d": platform_fee_due_30d,
        "chart": chart,
    }


# -----------------------------------------------------------------------------
# Alerts Pack (used by /platform/metrics/alerts/)
# -----------------------------------------------------------------------------
def alerts_pack() -> Dict[str, Any]:
    """
    Keep this lightweight + stable. UI can render:
      - executive summary
      - list of alerts
    """
    Business = _safe_model("user_accounts", "Business")
    Ticket = _safe_model("user_accounts", "Ticket")

    today = timezone.localdate()
    now = timezone.now()

    # Tickets aging (best-effort)
    tickets_open = 0
    aging_24 = 0
    aging_48 = 0
    aging_72 = 0

    if Ticket is not None:
        try:
            # open-ish statuses vary. try common ones.
            fields = {f.name for f in Ticket._meta.get_fields() if hasattr(f, "name")}
            if "status" in fields:
                open_q = Q(status__iexact="OPEN") | Q(status__iexact="NEW") | Q(status__iexact="PENDING")
                tickets_open = Ticket.objects.filter(open_q).count()
                aging_24 = Ticket.objects.filter(open_q, created_at__lte=now - timedelta(hours=24)).count()
                aging_48 = Ticket.objects.filter(open_q, created_at__lte=now - timedelta(hours=48)).count()
                aging_72 = Ticket.objects.filter(open_q, created_at__lte=now - timedelta(hours=72)).count()
            else:
                # fallback: count all as open
                tickets_open = Ticket.objects.count()
        except Exception:
            pass

    locked_businesses = 0
    missing_card = 0
    if Business is not None:
        try:
            locked_businesses = Business.objects.filter(_biz_locked_q(Business)).count()
        except Exception:
            locked_businesses = 0
        try:
            # missing card = NOT card_on_file
            missing_card = Business.objects.exclude(_biz_card_on_file_q(Business)).count()
        except Exception:
            missing_card = 0

    # Basic “traffic light”
    def level(val: int, red_at: int, yellow_at: int) -> str:
        if val >= red_at:
            return "RED"
        if val >= yellow_at:
            return "YELLOW"
        return "GREEN"

    alerts = [
        {
            "key": "tickets_aging_24h",
            "label": "Tickets aging > 24h",
            "value": aging_24,
            "status": level(aging_24, red_at=10, yellow_at=3),
        },
        {
            "key": "businesses_locked",
            "label": "Locked businesses",
            "value": locked_businesses,
            "status": level(locked_businesses, red_at=1, yellow_at=1),
        },
        {
            "key": "missing_card",
            "label": "Businesses missing card",
            "value": missing_card,
            "status": level(missing_card, red_at=10, yellow_at=3),
        },
    ]

    red = sum(1 for a in alerts if a["status"] == "RED")
    yellow = sum(1 for a in alerts if a["status"] == "YELLOW")
    green = sum(1 for a in alerts if a["status"] == "GREEN")

    return {
        "executive": {
            "day": today.isoformat(),
            "gmv_today_cents": 0,
            "platform_revenue_today_cents": 0,
            "new_businesses_today": 0,
            "tickets_open": tickets_open,
            "tickets_aging_gt_24h": aging_24,
            "tickets_aging_gt_48h": aging_48,
            "tickets_aging_gt_72h": aging_72,
            "rent_collected_today_cents": 0,
            "ad_revenue_today_cents": 0,
            "alerts_count": red + yellow,
            "billing": {
                "locked_businesses": locked_businesses,
                "businesses_missing_card": missing_card,
            },
        },
        "alerts": alerts,
        "alerts_red": red,
        "alerts_yellow": yellow,
        "alerts_green": green,
    }