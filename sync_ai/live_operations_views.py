from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, Ticket, TicketOperationalProfile, WorkforceProfile
from .dispatch_views import CLOSED, _geocode, _risk_for, _ticket_address, estimate_travel
from .workforce_views import _business_for_request


def _member_for_employee(request):
    raw = request.headers.get("X-Business-ID") or request.query_params.get("business_id")
    qs = BusinessMember.objects.select_related("business", "user").filter(user=request.user, is_active=True, business__is_active=True)
    if raw:
        try:
            qs = qs.filter(business_id=int(raw))
        except (TypeError, ValueError):
            pass
    member = qs.order_by("business_id").first()
    if member:
        return member
    owned = Business.objects.filter(owner=request.user, is_active=True).order_by("id").first()
    if owned:
        member, _ = BusinessMember.objects.get_or_create(
            business=owned,
            user=request.user,
            defaults={"role": "OWNER", "is_active": True},
        )
        return member
    return None


def live_travel(origin: str, destination: str):
    """Prefer Google's traffic-aware duration; fall back to Build 16 estimate."""
    if not origin or not destination or origin.strip().lower() == destination.strip().lower():
        return {"minutes": 0, "miles": 0.0, "basis": "same_or_missing_location", "traffic_minutes": 0}
    key = os.getenv("GOOGLE_MAPS_SERVER_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if key:
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={
                    "origins": origin,
                    "destinations": destination,
                    "departure_time": "now",
                    "traffic_model": "best_guess",
                    "key": key,
                },
                timeout=5,
            )
            data = response.json()
            element = (((data.get("rows") or [{}])[0].get("elements") or [{}])[0])
            if element.get("status") == "OK":
                normal = int(round((element.get("duration", {}).get("value") or 0) / 60))
                traffic = int(round((element.get("duration_in_traffic", {}).get("value") or element.get("duration", {}).get("value") or 0) / 60))
                miles = round((element.get("distance", {}).get("value") or 0) / 1609.344, 1)
                return {
                    "minutes": max(0, traffic),
                    "traffic_minutes": max(0, traffic),
                    "normal_minutes": max(0, normal),
                    "traffic_delay_minutes": max(0, traffic - normal),
                    "miles": miles,
                    "basis": "google_live_traffic",
                }
        except Exception:
            pass
    fallback = estimate_travel(origin, destination)
    return {
        **fallback,
        "traffic_minutes": fallback.get("minutes", 0),
        "normal_minutes": fallback.get("minutes", 0),
        "traffic_delay_minutes": 0,
    }


WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    95: "Thunderstorms",
    96: "Thunderstorms / hail",
    99: "Severe thunderstorms / hail",
}


def weather_for_address(address: str, at_time=None):
    point = _geocode(address)
    if not point:
        return {"available": False, "basis": "location_unavailable"}
    lat, lon = point
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
                "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 2,
                "timezone": "auto",
            },
            timeout=5,
        )
        data = response.json()
        current = data.get("current") or {}
        result = {
            "available": True,
            "basis": "open_meteo",
            "temperature_f": current.get("temperature_2m"),
            "precipitation": current.get("precipitation"),
            "wind_mph": current.get("wind_speed_10m"),
            "weather_code": current.get("weather_code"),
            "condition": WEATHER_CODES.get(current.get("weather_code"), "Weather available"),
            "scheduled": None,
        }
        if at_time:
            target = at_time.astimezone(timezone.get_current_timezone()) if timezone.is_aware(at_time) else at_time
            hourly = data.get("hourly") or {}
            times = hourly.get("time") or []
            if times:
                best_i = None
                best_delta = None
                for i, raw in enumerate(times):
                    try:
                        candidate = datetime.fromisoformat(raw)
                        delta = abs((candidate.replace(tzinfo=None) - target.replace(tzinfo=None)).total_seconds())
                    except Exception:
                        continue
                    if best_delta is None or delta < best_delta:
                        best_i, best_delta = i, delta
                if best_i is not None:
                    code = (hourly.get("weather_code") or [None] * len(times))[best_i]
                    result["scheduled"] = {
                        "time": times[best_i],
                        "temperature_f": (hourly.get("temperature_2m") or [None] * len(times))[best_i],
                        "precip_probability": (hourly.get("precipitation_probability") or [None] * len(times))[best_i],
                        "precipitation": (hourly.get("precipitation") or [None] * len(times))[best_i],
                        "wind_mph": (hourly.get("wind_speed_10m") or [None] * len(times))[best_i],
                        "condition": WEATHER_CODES.get(code, "Weather available"),
                    }
        return result
    except Exception:
        return {"available": False, "basis": "weather_provider_unavailable"}


def _clock_payload(ops: TicketOperationalProfile, now=None):
    now = now or timezone.now()
    running = bool(ops.actual_started_at and not ops.actual_finished_at)
    seconds = int(ops.actual_work_seconds or 0)
    if running:
        seconds += max(0, int((now - ops.actual_started_at).total_seconds()))
    return {
        "running": running,
        "started_at": ops.actual_started_at.isoformat() if ops.actual_started_at else None,
        "finished_at": ops.actual_finished_at.isoformat() if ops.actual_finished_at else None,
        "elapsed_seconds": seconds,
    }


def _employee_job_payload(ticket, previous_address=""):
    ops, _ = TicketOperationalProfile.objects.get_or_create(ticket=ticket)
    address = _ticket_address(ticket)
    travel = live_travel(previous_address, address)
    weather = weather_for_address(address, ops.scheduled_start)
    return {
        "ticket_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "title": ticket.work_title or getattr(ticket.service_request, "title", "") or "Service job",
        "status": ticket.status,
        "priority": ops.priority,
        "address": address,
        "scheduled_start": ops.scheduled_start.isoformat() if ops.scheduled_start else None,
        "scheduled_end": ops.scheduled_end.isoformat() if ops.scheduled_end else None,
        "expected_finish_at": ops.expected_finish_at.isoformat() if ops.expected_finish_at else None,
        "due_at": ops.due_at.isoformat() if ops.due_at else None,
        "risk": _risk_for(ticket),
        "travel": travel,
        "weather": weather,
        "clock": _clock_payload(ops),
        "customer_visible_note": ops.customer_visible_note,
        "internal_note": ops.internal_note,
    }


class EmployeeLiveDayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = _member_for_employee(request)
        if not member:
            return Response({"detail": "You are not attached to an active Business team."}, status=404)
        day_raw = request.query_params.get("date")
        try:
            day = datetime.fromisoformat(day_raw).date() if day_raw else timezone.localdate()
        except ValueError:
            return Response({"detail": "Use YYYY-MM-DD for date."}, status=400)
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
        end = start + timedelta(days=1)
        jobs = list(
            Ticket.objects.select_related("service_request", "operations_profile")
            .filter(assigned_business=member.business, assigned_member=request.user)
            .exclude(status__in=CLOSED)
            .filter(operations_profile__scheduled_start__gte=start, operations_profile__scheduled_start__lt=end)
            .order_by("operations_profile__scheduled_start")
        )
        profile, _ = WorkforceProfile.objects.get_or_create(member=member)
        previous = profile.route_start_address or ""
        rows = []
        for ticket in jobs:
            row = _employee_job_payload(ticket, previous)
            rows.append(row)
            previous = row["address"] or previous
        active = next((row for row in rows if row["clock"]["running"]), None)
        next_job = next((row for row in rows if row["status"] not in CLOSED), None)
        return Response({
            "business_id": member.business_id,
            "business_name": member.business.name,
            "member_id": member.id,
            "role": member.role,
            "date": day.isoformat(),
            "active_job": active,
            "next_job": next_job,
            "jobs": rows,
            "summary": {
                "jobs": len(rows),
                "at_risk": sum(1 for row in rows if row["risk"] in {"AT_RISK", "LATE"}),
                "traffic_delay_minutes": sum(int(row["travel"].get("traffic_delay_minutes") or 0) for row in rows),
            },
        })


class EmployeeJobClockView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ticket_id: int):
        member = _member_for_employee(request)
        if not member:
            return Response({"detail": "Business team membership required."}, status=403)
        ticket = (
            Ticket.objects.select_for_update()
            .select_related("operations_profile", "assigned_business")
            .filter(pk=ticket_id, assigned_business=member.business, assigned_member=request.user)
            .first()
        )
        if not ticket:
            return Response({"detail": "This job is not assigned to you."}, status=404)
        action = str(request.data.get("action") or "").strip().lower()
        if action not in {"start", "finish"}:
            return Response({"detail": "action must be start or finish."}, status=400)
        ops, _ = TicketOperationalProfile.objects.select_for_update().get_or_create(ticket=ticket)
        now = timezone.now()
        if action == "start":
            # Do not allow one technician to run two job clocks simultaneously.
            other = TicketOperationalProfile.objects.filter(
                ticket__assigned_business=member.business,
                ticket__assigned_member=request.user,
                actual_started_at__isnull=False,
                actual_finished_at__isnull=True,
            ).exclude(ticket=ticket).first()
            if other:
                return Response({"detail": "Finish your current job clock before starting another.", "active_ticket_id": other.ticket_id}, status=409)
            if not ops.actual_started_at or ops.actual_finished_at:
                ops.actual_started_at = now
                ops.actual_finished_at = None
                ops.actual_work_seconds = 0
            if ticket.status in {"ASSIGNED", "ACCEPTED", "SCHEDULED", "EN_ROUTE", "ON_SITE"}:
                ticket.status = "IN_PROGRESS"
                ticket.save(update_fields=["status", "updated_at"])
        else:
            if ops.actual_started_at and not ops.actual_finished_at:
                ops.actual_work_seconds = max(0, int((now - ops.actual_started_at).total_seconds()))
                ops.actual_finished_at = now
            if ticket.status == "IN_PROGRESS":
                ticket.status = "COMPLETED"
                ticket.save(update_fields=["status", "updated_at"])
        ops.save(update_fields=["actual_started_at", "actual_finished_at", "actual_work_seconds", "updated_at"])
        return Response({"ticket_id": ticket.id, "status": ticket.status, "clock": _clock_payload(ops, now)})


class BusinessLiveOperationsView(APIView):
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
        if business.owner_id != request.user.id and not (member and (member.can_manage_schedule or member.can_assign_tickets or member.can_manage_team)):
            return Response({"detail": "Dispatch or schedule permission required."}, status=403)
        day_raw = request.query_params.get("date")
        try:
            day = datetime.fromisoformat(day_raw).date() if day_raw else timezone.localdate()
        except ValueError:
            return Response({"detail": "Use YYYY-MM-DD for date."}, status=400)
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
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
            for p in WorkforceProfile.objects.select_related("member", "member__user").filter(member__business=business, member__is_active=True, is_schedulable=True)
        }
        grouped = {}
        for ticket in tickets:
            grouped.setdefault(ticket.assigned_member_id, []).append(ticket)
        staff = []
        recommendations = []
        for user_id, profile in profiles.items():
            previous_address = profile.route_start_address or ""
            previous_end = start
            jobs = []
            for ticket in grouped.get(user_id, []):
                ops = ticket.operations_profile
                travel = live_travel(previous_address, _ticket_address(ticket))
                required_gap = int(travel.get("minutes") or 0) + int(profile.default_buffer_minutes or 0)
                available_gap = max(0, int(((ops.scheduled_start - previous_end).total_seconds()) // 60)) if previous_end > start else None
                conflict = available_gap is not None and available_gap < required_gap
                risk = _risk_for(ticket)
                if conflict and risk == "ON_TIME":
                    risk = "AT_RISK"
                weather = weather_for_address(_ticket_address(ticket), ops.scheduled_start)
                clock = _clock_payload(ops)
                row = {
                    "ticket_id": ticket.id,
                    "title": ticket.work_title or getattr(ticket.service_request, "title", "") or "Service job",
                    "status": ticket.status,
                    "priority": ops.priority,
                    "address": _ticket_address(ticket),
                    "scheduled_start": ops.scheduled_start.isoformat() if ops.scheduled_start else None,
                    "scheduled_end": ops.scheduled_end.isoformat() if ops.scheduled_end else None,
                    "expected_finish_at": ops.expected_finish_at.isoformat() if ops.expected_finish_at else None,
                    "risk": risk,
                    "route_conflict": conflict,
                    "available_gap_minutes": available_gap,
                    "required_gap_minutes": required_gap,
                    "travel": travel,
                    "weather": weather,
                    "clock": clock,
                }
                jobs.append(row)
                if conflict:
                    recommendations.append({
                        "type": "ROUTE_CONFLICT",
                        "ticket_id": ticket.id,
                        "severity": "HIGH" if risk == "LATE" else "MEDIUM",
                        "message": f"{profile.member.user.get_full_name() or profile.member.user.email} needs about {required_gap} minutes for travel + buffer but has {available_gap}.",
                        "action": "Review reassignment or adjust timing",
                    })
                if travel.get("traffic_delay_minutes", 0) >= 10:
                    recommendations.append({
                        "type": "TRAFFIC",
                        "ticket_id": ticket.id,
                        "severity": "MEDIUM",
                        "message": f"Live traffic adds about {travel['traffic_delay_minutes']} minutes before this job.",
                        "action": "Review ETA",
                    })
                scheduled_weather = (weather or {}).get("scheduled") or {}
                if (scheduled_weather.get("precip_probability") or 0) >= 60:
                    recommendations.append({
                        "type": "WEATHER",
                        "ticket_id": ticket.id,
                        "severity": "MEDIUM",
                        "message": f"Weather risk: {scheduled_weather.get('precip_probability')}% precipitation near the scheduled time.",
                        "action": "Review outdoor work timing",
                    })
                previous_address = _ticket_address(ticket) or previous_address
                previous_end = ops.expected_finish_at or ops.scheduled_end or previous_end
            staff.append({
                "member_id": profile.member_id,
                "user_id": user_id,
                "name": profile.member.user.get_full_name() or profile.member.user.email,
                "title": profile.title or profile.member.get_role_display(),
                "route_start_address": profile.route_start_address,
                "jobs": jobs,
            })
        return Response({
            "business_id": business.id,
            "date": day.isoformat(),
            "staff": staff,
            "recommendations": recommendations,
            "summary": {
                "scheduled_jobs": len(tickets),
                "active_clocks": sum(1 for row in staff for job in row["jobs"] if job["clock"]["running"]),
                "at_risk_or_late": sum(1 for row in staff for job in row["jobs"] if job["risk"] in {"AT_RISK", "LATE"}),
                "route_conflicts": sum(1 for row in staff for job in row["jobs"] if job["route_conflict"]),
                "traffic_delay_minutes": sum(int(job["travel"].get("traffic_delay_minutes") or 0) for row in staff for job in row["jobs"]),
            },
        })
