# backend/user_accounts/viewsets/ticket_metrics.py
from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional, Tuple

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


def _get_biz_and_validate_member(request):
    biz_id = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not biz_id:
        return None, Response({"detail": "Missing X-Business-Id header."}, status=400)

    Business = _get_model("user_accounts", "Business")
    BusinessMember = _get_model("user_accounts", "BusinessMember")
    Ticket = _get_model("user_accounts", "Ticket")

    if not Business or not BusinessMember or not Ticket:
        return None, Response(
            {"detail": "Missing Business/BusinessMember/Ticket models. Check app_label/model_name in ticket_metrics.py."},
            status=500,
        )

    try:
        biz = Business.objects.get(pk=int(biz_id))
    except Exception:
        return None, Response({"detail": "Invalid business id."}, status=400)

    user = request.user
    is_member = BusinessMember.objects.filter(business_id=biz.id, user_id=user.id).exists()
    if not is_member:
        return None, Response({"detail": "Not a member of this business."}, status=403)

    return (biz, Ticket), None


def _ticket_field_names(Ticket):
    return {f.name for f in Ticket._meta.fields}


def _minutes(dt_delta) -> Optional[float]:
    if dt_delta is None:
        return None
    try:
        return float(dt_delta.total_seconds() / 60.0)
    except Exception:
        return None


def _safe_div(n: float, d: float) -> float:
    return float(n) / float(d) if d else 0.0


def _pick_zip_field(Ticket) -> Optional[str]:
    f = _ticket_field_names(Ticket)
    if "service_zip" in f:
        return "service_zip"
    if "base_zip" in f:
        return "base_zip"
    return None


def _infer_primary_zip_for_business(Ticket, business_id: int, since_dt) -> str:
    """
    Gets the most common zip for the business based on recent assigned tickets.
    """
    zip_field = _pick_zip_field(Ticket)
    if not zip_field:
        return ""

    qs = Ticket.objects.filter(assigned_business_id=business_id, created_at__gte=since_dt)
    if zip_field == "service_zip":
        row = (
            qs.exclude(service_zip__isnull=True)
            .exclude(service_zip__exact="")
            .values("service_zip")
            .annotate(c=Count("id"))
            .order_by("-c")
            .first()
        )
        return str(row["service_zip"]) if row and row.get("service_zip") else ""

    row = (
        qs.exclude(base_zip__isnull=True)
        .exclude(base_zip__exact="")
        .values("base_zip")
        .annotate(c=Count("id"))
        .order_by("-c")
        .first()
    )
    return str(row["base_zip"]) if row and row.get("base_zip") else ""


class TicketZipMetricsAPIView(APIView):
    """
    GET /api/v1/tickets/metrics/zip/
    Auth required.
    X-Business-Id required.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pair, err = _get_biz_and_validate_member(request)
        if err:
            return err

        biz, Ticket = pair

        now = timezone.now()
        since_30 = now - timedelta(days=30)
        since_60 = now - timedelta(days=60)

        zip_field = _pick_zip_field(Ticket)
        if not zip_field:
            return Response(
                {"detail": "Ticket model missing service_zip/base_zip. Add a zip field or update metrics logic."},
                status=500,
            )

        # Determine ZIP to compare within
        zip_code = _infer_primary_zip_for_business(Ticket, biz.id, since_30)

        # Fallback to business fields if you store zip on business
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
                    "zip": "",
                    "window_days": {"response": 30, "volume": 30, "completion": 60},
                    "my": {
                        "business_id": biz.id,
                        "business_name": getattr(biz, "name", f"Business #{biz.id}"),
                        "zip": "",
                        "avg_response_min_30d": None,
                        "fast_accept_10m_30d": 0,
                        "jobs_completed_30d": 0,
                        "completion_rate_60d": 0.0,
                        "accept_count_30d": 0,
                    },
                    "leaderboard": [],
                    "detail": "No ZIP found yet. Create tickets with service_zip/base_zip or set business zip.",
                }
            )

        # -------------------------
        # My metrics
        # -------------------------
        my_30 = Ticket.objects.filter(assigned_business_id=biz.id, created_at__gte=since_30)
        my_completed_30 = my_30.filter(status__in=["COMPLETED", "PAID", "CLOSED"]).count()
        my_accept_30 = my_30.filter(accepted_at__isnull=False).count()

        my_fast_accept_10m = my_30.filter(
            accepted_at__isnull=False,
            accepted_at__lte=F("created_at") + timedelta(minutes=10),
        ).count()

        avg_response_min = None
        try:
            delta_avg = (
                my_30.filter(accepted_at__isnull=False)
                .annotate(delta=F("accepted_at") - F("created_at"))
                .aggregate(avg=Avg("delta"))
                .get("avg")
            )
            avg_response_min = _minutes(delta_avg)
        except Exception:
            # fallback: don't block endpoint
            avg_response_min = None

        my_60 = Ticket.objects.filter(assigned_business_id=biz.id, created_at__gte=since_60).exclude(
            status__in=["CANCELLED"]
        )
        my_total_60 = my_60.count()
        my_completed_60 = my_60.filter(status__in=["COMPLETED", "PAID", "CLOSED"]).count()
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
        # Leaderboard for same ZIP
        # -------------------------
        base30 = (
            Ticket.objects.filter(created_at__gte=since_30)
            .exclude(assigned_business__isnull=True)
            .filter(**{zip_field: zip_code})
        )

        rows = (
            base30.values("assigned_business_id")
            .annotate(
                accept_count_30d=Count("id", filter=Q(accepted_at__isnull=False)),
                jobs_completed_30d=Count("id", filter=Q(status__in=["COMPLETED", "PAID", "CLOSED"])),
                fast_accept_10m_30d=Count(
                    "id",
                    filter=Q(accepted_at__isnull=False)
                    & Q(accepted_at__lte=F("created_at") + timedelta(minutes=10)),
                ),
            )
            .order_by()
        )

        Business = biz.__class__
        biz_ids = [r["assigned_business_id"] for r in rows if r.get("assigned_business_id") is not None]
        name_map = {b.id: getattr(b, "name", f"Business #{b.id}") for b in Business.objects.filter(id__in=biz_ids)}

        base60 = (
            Ticket.objects.filter(created_at__gte=since_60)
            .exclude(assigned_business__isnull=True)
            .filter(**{zip_field: zip_code})
            .exclude(status__in=["CANCELLED"])
        )

        totals60 = (
            base60.values("assigned_business_id")
            .annotate(
                total=Count("id"),
                completed=Count("id", filter=Q(status__in=["COMPLETED", "PAID", "CLOSED"])),
            )
            .order_by()
        )
        totals60_map = {r["assigned_business_id"]: r for r in totals60}

        avg_map: Dict[int, Optional[float]] = {}
        try:
            deltas = (
                base30.filter(accepted_at__isnull=False)
                .values("assigned_business_id")
                .annotate(avg=Avg(F("accepted_at") - F("created_at")))
                .order_by()
            )
            for r in deltas:
                avg_map[int(r["assigned_business_id"])] = _minutes(r["avg"])
        except Exception:
            avg_map = {}

        leaderboard = []
        for r in rows:
            bid = int(r["assigned_business_id"])
            t60 = totals60_map.get(bid, {"total": 0, "completed": 0})
            completion_rate = _safe_div(float(t60.get("completed", 0)), float(t60.get("total", 0)))

            leaderboard.append(
                {
                    "business_id": bid,
                    "business_name": name_map.get(bid, f"Business #{bid}"),
                    "avg_response_min_30d": avg_map.get(bid),
                    "completion_rate_60d": round(completion_rate, 4),
                    "jobs_completed_30d": int(r.get("jobs_completed_30d") or 0),
                    "accept_count_30d": int(r.get("accept_count_30d") or 0),
                    "fast_accept_10m_30d": int(r.get("fast_accept_10m_30d") or 0),
                }
            )

        # Rankings
        def rank_low(items, key):
            clean = [(x["business_id"], x[key]) for x in items if x.get(key) is not None]
            clean.sort(key=lambda t: t[1])
            out = {}
            for i, (bid, _) in enumerate(clean, start=1):
                out[bid] = i
            return out

        def rank_high(items, key):
            clean = [(x["business_id"], float(x.get(key) or 0)) for x in items]
            clean.sort(key=lambda t: t[1], reverse=True)
            out = {}
            for i, (bid, _) in enumerate(clean, start=1):
                out[bid] = i
            return out

        resp_rank = rank_low(leaderboard, "avg_response_min_30d")
        comp_rank = rank_high(leaderboard, "completion_rate_60d")
        vol_rank = rank_high(leaderboard, "jobs_completed_30d")

        for x in leaderboard:
            bid = x["business_id"]
            x["rank_response"] = resp_rank.get(bid)
            x["rank_completion"] = comp_rank.get(bid)
            x["rank_volume"] = vol_rank.get(bid)

        # Put "my business" first
        leaderboard.sort(key=lambda x: (0 if x["business_id"] == biz.id else 1, x.get("rank_response") or 999999))

        return Response(
            {
                "zip": zip_code,
                "window_days": {"response": 30, "volume": 30, "completion": 60},
                "my": my_payload,
                "leaderboard": leaderboard,
            }
        )