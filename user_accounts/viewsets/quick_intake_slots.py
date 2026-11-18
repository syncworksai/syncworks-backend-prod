"""Availability suggestions for quick business intake.

Suggestions respect existing technician commitments and configured working days.
They are proposals, not a reservation or a traffic-aware route guarantee.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Ticket, TicketOperationalProfile, BusinessMember, WorkforceProfile
from user_accounts.viewsets.business_quick_intake import _business_for_actor

BUSY_STATUS = {"ASSIGNED", "ACCEPTED", "SCHEDULED", "EN_ROUTE", "ON_SITE", "IN_PROGRESS", "NEEDS_QUOTE", "QUOTED", "APPROVED"}
WEEKDAYS = ("monday","tuesday","wednesday","thursday","friday","saturday","sunday")


def _timezone(value):
    try:
        return ZoneInfo(str(value or "America/Chicago"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("America/Chicago")


def _windows(profile, day):
    """Read workforce weekly availability where configured, else standard work hours."""
    availability = profile.weekly_availability if profile else {}
    if not isinstance(availability, dict) or not availability:
        return [(8*60, 17*60)]
    raw = availability.get(WEEKDAYS[day.weekday()])
    if raw is None:
        raw = availability.get(WEEKDAYS[day.weekday()][:3])
    if raw is None:
        raw = availability.get(str(day.weekday()))
    if raw is None:
        return []
    if isinstance(raw, dict):
        if raw.get("open") is False or raw.get("enabled") is False:
            return []
        raw = [raw]
    if not isinstance(raw, list):
        return []
    output = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False or entry.get("open") is False:
            continue
        start = str(entry.get("start") or entry.get("from") or "")
        end = str(entry.get("end") or entry.get("to") or "")
        try:
            s = int(start[:2])*60 + int(start[3:5])
            e = int(end[:2])*60 + int(end[3:5])
            if 0 <= s < e <= 1440:
                output.append((s,e))
        except (ValueError,TypeError):
            pass
    return output


class QuickIntakeSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _ = _business_for_actor(request)
        priority = str(request.query_params.get("priority") or "STANDARD").upper()
        if priority not in {"EMERGENCY","URGENT","STANDARD","FLEXIBLE"}:
            return Response({"detail":"Invalid priority."},status=400)
        try:
            duration = int(request.query_params.get("duration") or 60)
        except (TypeError,ValueError):
            return Response({"detail":"Invalid duration."},status=400)
        if not 15 <= duration <= 1440:
            return Response({"detail":"Duration must be between 15 and 1440 minutes."},status=400)
        tz = _timezone(request.query_params.get("timezone"))
        now = timezone.now().astimezone(tz)
        candidate_start = now.replace(minute=0,second=0,microsecond=0) + timedelta(hours=1)
        earliest_day = {
            "EMERGENCY":0,"URGENT":1,"STANDARD":0,"FLEXIBLE":0
        }[priority]
        if earliest_day:
            candidate_start = (now+timedelta(days=earliest_day)).replace(hour=8,minute=0,second=0,microsecond=0)
        try:
            requested_user_id = int(request.query_params.get("technician_id") or 0)
        except (ValueError,TypeError):
            return Response({"detail":"Invalid technician."},status=400)
        membership = None
        profile = None
        if requested_user_id:
            membership = BusinessMember.objects.filter(business=business,user_id=requested_user_id,is_active=True).first()
            if not membership:
                return Response({"detail":"Technician is not part of the selected business."},status=400)
            profile = WorkforceProfile.objects.filter(member=membership,is_schedulable=True).first()
            if not profile:
                return Response({"detail":"This technician is not schedulable."},status=400)
        until = now + timedelta(days=15)
        events = []
        if membership:
            events = list(TicketOperationalProfile.objects.filter(
                ticket__assigned_business=business,ticket__assigned_member_id=membership.user_id,
                ticket__status__in=BUSY_STATUS, scheduled_start__lt=until,
                scheduled_end__gt=now,
            ).values_list("scheduled_start","scheduled_end"))
        padding = timedelta(minutes=(profile.default_buffer_minutes if profile else 15))
        suggestions = []
        cur = candidate_start
        while cur < until and len(suggestions)<5:
            day = cur.date()
            minutes = cur.hour*60 + cur.minute
            windows = _windows(profile,day)
            end = cur + timedelta(minutes=duration)
            same_day = end.date() == day
            fits = same_day and any(start <= minutes and minutes+duration <= stop for start,stop in windows)
            if fits:
                free = all(end+padding<=a.astimezone(tz) or cur-padding>=b.astimezone(tz) for a,b in events if a and b)
                if free:
                    suggestions.append({"start":cur.isoformat(),"end":end.isoformat()})
            cur += timedelta(minutes=30)
        return Response({
            "suggestions":suggestions,
            "priority":priority,"technician_id":requested_user_id or None,
            "timezone":str(tz),
            "verified_route":False,
            "note":"Suggestions check configured work windows and saved appointments, not live traffic, travel duration, or temporary holds. Review before confirming.",
        })
