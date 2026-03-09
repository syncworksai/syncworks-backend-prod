# backend/tickets/metrics_api.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.apps import apps
from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def _get_business_and_member(request):
    """
    Uses X-Business-Id header used across SyncWorks.
    Validates membership (BusinessMember) to prevent leaking leaderboard data.
    """
    biz_id = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not biz_id:
        return None, None, Response({"detail": "Missing X-Business-Id header."}, status=400)

    Business = _get_model("user_accounts", "Business") or _get_model("businesses", "Business")
    BusinessMember = _get_model("user_accounts", "BusinessMember") or _get_model("businesses", "BusinessMember")

    if not Business or not BusinessMember:
        return None, None, Response(
            {
                "detail": "Business/BusinessMember model not found. "
                          "Update _get_model() app_label guesses in backend/tickets/metrics_api.py."
            },
            status=500,
        )

    try:
        biz = Business.objects.get(pk=int(biz_id))
    except Exception:
        return None, None, Response({"detail": "Invalid business id."}, status=400)

    user = request.user
    is_member = BusinessMember.objects.filter(business_id=biz.id, user_id=user.id).exists()
    if not is_member:
        return None, None, Response({"detail": "Not a member of this business."}, status=403)

    return biz, user, None


def _pick_zip_from_business_tickets(Ticket, business_id: int, since_dt) -> str:
    """
    Attempts to find a "primary" zip for the business based on recent tickets.
    Prefers service_zip; falls back to base_zip if present.
    """
    qs = Ticket.objects.filter(assigned_business_id=business_id, created_at__gte=since_dt)

    # Try service_zip first
    if "service_zip" in [f.name for f in Ticket._meta.fields]:
        z = (
            qs.exclude(service_zip__isnull=True)
            .exclude(service_zip__exact="")
            .values("service_zip")
            .annotate(c=Count("id"))
            .order_by("-c")
            .first()
        )
        if z and z.get("service_zip"):
            return str(z["service_zip"])

    # Fall back to base_zip (if exists)
    if "base_zip" in [f.name for f in Ticket._meta.fields]:
        z = (
            qs.exclude(base_zip__isnull=True)
            .exclude(base_zip__exact="")
            .values("base_zip")
            .annotate(c=Count("id"))
            .order_by("-c")
            .first()
        )
        if z and z.get("base_zip"):
            return str(z["base_zip"])

    return ""


def _minutes(dt_delta) -> Optional[float]:
    if dt_delta is None:
        return None
    try:
        return float(dt_delta.total_seconds() / 60.0)
    except Exception:
        return None


def _safe_div(n: float, d: float) -> float:
    return float(n) / float(d) if d else 0.0


@dataclass
class BizRow:
    business_id: int
    business_name: str
    jobs_completed_30d: int
    accept_count_30d: int
    completion_rate_60d: float
    avg_response_min_30d: Optional[float]
    fast_accept_10m_30d: int


class SboZipMetricsView(APIView):
    """
    GET /api/v1/tickets/metrics/zip/
    Requires:
      - Auth token
      - X-Business-Id
    Returns:
      - my business metrics
      - leaderboard for businesses that have ticket activity in same ZIP in last 30 days
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        biz, user, err_resp = _get_business_and_member(request)
        if err_resp:
            return err_resp

        Ticket = _get_model("user_accounts", "Ticket") or _get_model("tickets", "Ticket")
        if not Ticket:
            return Response(
                {"detail": "Ticket model not found. Update model lookup in backend/tickets/metrics_api.py."},
                status=500,
            )

        now = timezone.now()
        since_30 = now - timedelta(days=30)
        since_60 = now - timedelta(days=60)

        # Determine the ZIP we compare within
        zip_code = _pick_zip_from_business_tickets(Ticket, biz.id, since_30)

        # If no zip found from tickets, attempt to use Business.base_zip / zip / postal_code fields
        if not zip_code:
            for field in ["base_zip", "zip", "postal_code", "zip_code"]:
                if hasattr(biz, field):
                    v = getattr(biz, field, "") or ""
                    if str(v).strip():
                        zip_code = str(v).strip()
                        break

        if not zip_code:
            return Response(
                {
                    "detail": "No ZIP found for this business yet. Create/complete at least 1 ticket with service_zip (or set business zip).",
                    "zip": "",
                    "my": {},
                    "leaderboard": [],
                },
                status=200,
            )

        # Helper: pick which ticket field stores the zip used by marketplace matching
        ticket_fields = [f.name for f in Ticket._meta.fields]
        zip_field = "service_zip" if "service_zip" in ticket_fields else ("base_zip" if "base_zip" in ticket_fields else None)
        if not zip_field:
            return Response(
                {"detail": "Ticket has no service_zip/base_zip field. Add one or update metrics_api to match your schema."},
                status=500,
            )

        # -------------------------
        # Compute "my business" metrics
        # -------------------------
        my_tickets_30 = Ticket.objects.filter(assigned_business_id=biz.id, created_at__gte=since_30)
        my_completed_30 = my_tickets_30.filter(status__in=["COMPLETED", "PAID", "CLOSED"]).count()

        my_accept_30 = my_tickets_30.filter(accepted_at__isnull=False).count()
        my_fast_accept_10m = my_tickets_30.filter(
            accepted_at__isnull=False,
            created_at__gte=since_30,
            accepted_at__lte=F("created_at") + timedelta(minutes=10),
        ).count()

        # Avg response time = avg(accepted_at - created_at) where accepted_at exists
        # NOTE: timedelta Avg works in PostgreSQL; in SQLite you may not get Avg delta directly.
        # We compute a fallback in Python if DB Avg fails.
        avg_response_min = None
        try:
            delta_avg = (
                my_tickets_30.filter(accepted_at__isnull=False)
                .annotate(delta=F("accepted_at") - F("created_at"))
                .aggregate(avg=Avg("delta"))
                .get("avg")
            )
            avg_response_min = _minutes(delta_avg)
        except Exception:
            # Python fallback
            times = []
            for t in my_tickets_30.filter(accepted_at__isnull=False).only("created_at", "accepted_at")[:5000]:
                if t.accepted_at and t.created_at:
                    times.append((t.accepted_at - t.created_at).total_seconds() / 60.0)
            avg_response_min = float(sum(times) / len(times)) if times else None

        # Completion rate (60d): completed / accepted (or started)
        my_tickets_60 = Ticket.objects.filter(assigned_business_id=biz.id, created_at__gte=since_60)
        my_completed_60 = my_tickets_60.filter(status__in=["COMPLETED", "PAID", "CLOSED"]).count()
        my_total_60 = my_tickets_60.exclude(status__in=["CANCELLED"]).count()
        my_completion_rate_60 = _safe_div(my_completed_60, my_total_60)

        my_payload = {
            "business_id": biz.id,
            "business_name": getattr(biz, "name", f"Business #{biz.id}"),
            "zip": zip_code,
            "avg_response_min_30d": avg_response_min,
            "fast_accept_10m_30d": my_fast_accept_10m,
            "jobs_completed_30d": my_completed_30,
            "completion_rate_60d": round(my_completion_rate_60, 4),
            "accept_count_30d": my_accept_30,
        }

        # -------------------------
        # Leaderboard: businesses with ticket activity in this ZIP in last 30d
        # -------------------------
        # We only consider tickets that are assigned to a business (otherwise "marketplace queue" / unassigned noise).
        base = Ticket.objects.filter(created_at__gte=since_30).exclude(assigned_business__isnull=True)
        base = base.filter(**{zip_field: zip_code})

        # If assigned_business is FK, Django creates assigned_business_id.
        rows = (
            base.values("assigned_business_id")
            .annotate(
                accept_count_30d=Count("id", filter=Q(accepted_at__isnull=False)),
                jobs_completed_30d=Count("id", filter=Q(status__in=["COMPLETED", "PAID", "CLOSED"])),
                fast_accept_10m_30d=Count(
                    "id",
                    filter=Q(accepted_at__isnull=False) & Q(accepted_at__lte=F("created_at") + timedelta(minutes=10)),
                ),
            )
            .order_by()
        )

        # Map business names in one query
        Business = biz.__class__
        biz_ids = [r["assigned_business_id"] for r in rows if r.get("assigned_business_id") is not None]
        biz_names = {b.id: getattr(b, "name", f"Business #{b.id}") for b in Business.objects.filter(id__in=biz_ids)}

        # Compute completion rate 60d per business (one query per business would be slow; do aggregated by business)
        base60 = Ticket.objects.filter(created_at__gte=since_60).exclude(assigned_business__isnull=True)
        base60 = base60.filter(**{zip_field: zip_code})

        totals60 = (
            base60.values("assigned_business_id")
            .annotate(
                total=Count("id", filter=~Q(status__in=["CANCELLED"])),
                completed=Count("id", filter=Q(status__in=["COMPLETED", "PAID", "CLOSED"])),
            )
            .order_by()
        )
        totals60_map = {r["assigned_business_id"]: r for r in totals60}

        # Avg response per business (fallback: compute python per business is heavy, try DB first)
        avg_map: Dict[int, Optional[float]] = {}
        try:
            deltas = (
                base.filter(accepted_at__isnull=False)
                .values("assigned_business_id")
                .annotate(avg=Avg(F("accepted_at") - F("created_at")))
                .order_by()
            )
            for r in deltas:
                avg_map[r["assigned_business_id"]] = _minutes(r["avg"])
        except Exception:
            # Light fallback: skip avg response if DB can't do it
            avg_map = {}

        leaderboard: List[BizRow] = []
        for r in rows:
            bid = r["assigned_business_id"]
            t60 = totals60_map.get(bid, {"total": 0, "completed": 0})
            completion_rate = _safe_div(t60.get("completed", 0), t60.get("total", 0))

            leaderboard.append(
                BizRow(
                    business_id=int(bid),
                    business_name=biz_names.get(int(bid), f"Business #{bid}"),
                    jobs_completed_30d=int(r.get("jobs_completed_30d") or 0),
                    accept_count_30d=int(r.get("accept_count_30d") or 0),
                    completion_rate_60d=float(completion_rate),
                    avg_response_min_30d=avg_map.get(int(bid)),
                    fast_accept_10m_30d=int(r.get("fast_accept_10m_30d") or 0),
                )
            )

        # Rankings (lower response time is better, higher others better)
        def rank_low(values: List[Tuple[int, Optional[float]]]) -> Dict[int, int]:
            clean = [(bid, v) for bid, v in values if v is not None]
            clean.sort(key=lambda x: x[1])
            out = {}
            for i, (bid, _) in enumerate(clean, start=1):
                out[bid] = i
            return out

        def rank_high(values: List[Tuple[int, float]]) -> Dict[int, int]:
            clean = [(bid, v) for bid, v in values]
            clean.sort(key=lambda x: x[1], reverse=True)
            out = {}
            for i, (bid, _) in enumerate(clean, start=1):
                out[bid] = i
            return out

        resp_rank = rank_low([(b.business_id, b.avg_response_min_30d) for b in leaderboard])
        comp_rank = rank_high([(b.business_id, b.completion_rate_60d) for b in leaderboard])
        vol_rank = rank_high([(b.business_id, float(b.jobs_completed_30d)) for b in leaderboard])

        payload_leaderboard = []
        for b in leaderboard:
            payload_leaderboard.append(
                {
                    "business_id": b.business_id,
                    "business_name": b.business_name,
                    "avg_response_min_30d": b.avg_response_min_30d,
                    "completion_rate_60d": round(b.completion_rate_60d, 4),
                    "jobs_completed_30d": b.jobs_completed_30d,
                    "accept_count_30d": b.accept_count_30d,
                    "fast_accept_10m_30d": b.fast_accept_10m_30d,
                    "rank_response": resp_rank.get(b.business_id),
                    "rank_completion": comp_rank.get(b.business_id),
                    "rank_volume": vol_rank.get(b.business_id),
                }
            )

        # Put "my" at top for convenience
        payload_leaderboard.sort(key=lambda x: (0 if x["business_id"] == biz.id else 1, x.get("rank_response") or 999999))

        return Response(
            {
                "zip": zip_code,
                "window_days": {"response": 30, "volume": 30, "completion": 60},
                "my": my_payload,
                "leaderboard": payload_leaderboard,
            }
        )