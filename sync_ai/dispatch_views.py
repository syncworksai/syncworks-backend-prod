from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

import requests
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, Ticket, TicketOperationalProfile, WorkforceProfile
from .workforce_views import _business_for_request

CLOSED = {"COMPLETED", "PAID", "CLOSED", "CANCELLED"}


def _can_dispatch(member, business, user):
    return business.owner_id == user.id or bool(member and (member.can_manage_schedule or member.can_assign_tickets or member.can_manage_team))


def _geocode(address: str):
    address = (address or "").strip()
    key = os.getenv("GOOGLE_MAPS_SERVER_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if not address or not key:
        return None
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=4,
        )
        data = response.json()
        result = (data.get("results") or [None])[0]
        loc = ((result or {}).get("geometry") or {}).get("location") or {}
        if "lat" in loc and "lng" in loc:
            return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None
    return None


def _haversine_miles(a, b):
    if not a or not b:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(x))


def estimate_travel(origin: str, destination: str):
    if not origin or not destination or origin.strip().lower() == destination.strip().lower():
        return {"minutes": 0, "miles": 0.0, "basis": "same_or_missing_location"}
    miles = _haversine_miles(_geocode(origin), _geocode(destination))
    if miles is None:
        return {"minutes": 20, "miles": None, "basis": "fallback_estimate"}
    road_miles = miles * 1.25
    minutes = max(5, int(round((road_miles / 32.0) * 60)))
    return {"minutes": minutes, "miles": round(road_miles, 1), "basis": "geocoded_estimate"}


def _ticket_address(ticket):
    return (ticket.service_address or getattr(ticket.service_request, "address", "") or "").strip()


def _ops(ticket):
    return getattr(ticket, "operations_profile", None)


def _risk_for(ticket, now=None):
    now = now or timezone.now()
    ops = _ops(ticket)
    if ticket.status in CLOSED:
        return "DONE"
    if ops and ops.due_at and ops.due_at < now:
        return "LATE"
    if ops and ops.expected_finish_at and ops.due_at:
        remaining = (ops.due_at - ops.expected_finish_at).total_seconds() / 60
        if remaining < 0:
            return "LATE"
        if remaining <= 30:
            return "AT_RISK"
    return "ON_TIME"


def build_dispatch_board(business, date_value=None):
    day = date_value or timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), timezone.get_current_timezone())
    end = start + timedelta(days=1)
    tickets = list(
        Ticket.objects.select_related("assigned_member", "service_request", "operations_profile")
        .filter(assigned_business=business)
        .exclude(status__in=CLOSED)
        .filter(operations_profile__scheduled_start__gte=start, operations_profile__scheduled_start__lt=end)
        .order_by("assigned_member_id", "operations_profile__scheduled_start")
    )
    profiles = {
        p.member.user_id: p
        for p in WorkforceProfile.objects.select_related("member", "member__user").filter(
            member__business=business, member__is_active=True, is_schedulable=True
        )
    }
    by_user = {}
    for ticket in tickets:
        by_user.setdefault(ticket.assigned_member_id, []).append(ticket)

    staff_rows = []
    total_risk = 0
    for user_id, profile in profiles.items():
        person_tickets = by_user.get(user_id, [])
        previous_address = profile.route_start_address or ""
        previous_end = start
        jobs = []
        for ticket in person_tickets:
            ops = _ops(ticket)
            travel = estimate_travel(previous_address, _ticket_address(ticket))
            buffer_minutes = int(profile.default_buffer_minutes or 0)
            required_gap = travel["minutes"] + buffer_minutes
            available_gap = max(0, int(((ops.scheduled_start - previous_end).total_seconds()) // 60)) if ops and ops.scheduled_start else 0
            route_risk = bool(previous_end > start and available_gap < required_gap)
            risk = _risk_for(ticket)
            if route_risk and risk == "ON_TIME":
                risk = "AT_RISK"
            if risk in {"AT_RISK", "LATE"}:
                total_risk += 1
            jobs.append({
                "ticket_id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "title": ticket.work_title or getattr(ticket.service_request, "title", "") or "Service job",
                "status": ticket.status,
                "address": _ticket_address(ticket),
                "scheduled_start": ops.scheduled_start.isoformat() if ops and ops.scheduled_start else None,
                "scheduled_end": ops.scheduled_end.isoformat() if ops and ops.scheduled_end else None,
                "expected_finish_at": ops.expected_finish_at.isoformat() if ops and ops.expected_finish_at else None,
                "priority": ops.priority if ops else "STANDARD",
                "risk": risk,
                "travel_minutes": travel["minutes"],
                "travel_miles": travel["miles"],
                "travel_basis": travel["basis"],
                "available_gap_minutes": available_gap,
                "required_gap_minutes": required_gap,
                "route_conflict": route_risk,
            })
            previous_address = _ticket_address(ticket) or previous_address
            if ops and ops.scheduled_end:
                previous_end = ops.scheduled_end
        staff_rows.append({
            "member_id": profile.member_id,
            "user_id": user_id,
            "name": profile.member.user.get_full_name() or profile.member.user.email,
            "title": profile.title or profile.member.get_role_display(),
            "route_start_address": profile.route_start_address,
            "buffer_minutes": profile.default_buffer_minutes,
            "jobs": jobs,
        })
    return {
        "business_id": business.id,
        "date": day.isoformat(),
        "staff": staff_rows,
        "summary": {
            "schedulable_staff": len(staff_rows),
            "scheduled_jobs": len(tickets),
            "at_risk_or_late": total_risk,
        },
    }


class BusinessDispatchBoardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _business_for_request(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_dispatch(member, business, request.user):
            return Response({"detail": "Dispatch or schedule permission required."}, status=403)
        raw_date = request.query_params.get("date")
        try:
            day = datetime.fromisoformat(raw_date).date() if raw_date else timezone.localdate()
        except ValueError:
            return Response({"detail": "Use YYYY-MM-DD for date."}, status=400)
        return Response(build_dispatch_board(business, day))


class BusinessDispatchDelayView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_id: int):
        ticket = Ticket.objects.select_related("assigned_business", "operations_profile").filter(pk=ticket_id).first()
        if not ticket or not ticket.assigned_business_id:
            return Response({"detail": "Ticket not found."}, status=404)
        business = ticket.assigned_business
        member = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
        if not _can_dispatch(member, business, request.user):
            return Response({"detail": "Dispatch or schedule permission required."}, status=403)
        try:
            minutes = max(-240, min(480, int(request.data.get("minutes") or 0)))
        except (TypeError, ValueError):
            return Response({"detail": "minutes must be a number."}, status=400)
        ops, _ = TicketOperationalProfile.objects.get_or_create(ticket=ticket)
        if ops.scheduled_end:
            ops.scheduled_end += timedelta(minutes=minutes)
        if ops.expected_finish_at:
            ops.expected_finish_at += timedelta(minutes=minutes)
        elif ops.scheduled_end:
            ops.expected_finish_at = ops.scheduled_end
        ops.save(update_fields=["scheduled_end", "expected_finish_at", "updated_at"])
        return Response({
            "ticket_id": ticket.id,
            "delay_minutes": minutes,
            "scheduled_end": ops.scheduled_end.isoformat() if ops.scheduled_end else None,
            "expected_finish_at": ops.expected_finish_at.isoformat() if ops.expected_finish_at else None,
            "message": "Timing updated. SYNC will recalculate downstream route risk; no later appointment was moved automatically.",
        })
