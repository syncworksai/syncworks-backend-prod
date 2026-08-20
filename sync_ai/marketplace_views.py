from __future__ import annotations

from datetime import datetime, timedelta, time

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    Business,
    BusinessMember,
    ServiceCategory,
    ServiceRequest,
    Ticket,
    TicketOperationalProfile,
    WorkforceProfile,
)


ACTIVE_TICKET_STATUSES = {
    Ticket.Status.NEW,
    Ticket.Status.ASSIGNED,
    Ticket.Status.ACCEPTED,
    Ticket.Status.SCHEDULED,
    Ticket.Status.EN_ROUTE,
    Ticket.Status.ON_SITE,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.NEEDS_QUOTE,
    Ticket.Status.QUOTED,
    Ticket.Status.APPROVED,
    Ticket.Status.AWAITING_APPROVAL,
}

PRIORITY_SLA = {
    "EMERGENCY": {"response": 5, "assignment": 10, "arrival": 60, "completion": 240},
    "URGENT": {"response": 15, "assignment": 30, "arrival": 180, "completion": 480},
    "STANDARD": {"response": 120, "assignment": 240, "arrival": 1440, "completion": 2880},
    "FLEXIBLE": {"response": 480, "assignment": 1440, "arrival": 4320, "completion": 10080},
}


def _day_config(profile: WorkforceProfile, day_name: str):
    cfg = (profile.weekly_availability or {}).get(day_name, {})
    if not isinstance(cfg, dict) or not cfg.get("open"):
        return None
    try:
        start_h, start_m = [int(x) for x in str(cfg.get("start") or "08:00").split(":")[:2]]
        end_h, end_m = [int(x) for x in str(cfg.get("end") or "17:00").split(":")[:2]]
        return time(start_h, start_m), time(end_h, end_m)
    except Exception:
        return None


def _skill_match(profile: WorkforceProfile, requested: list[str]) -> bool:
    if not requested:
        return True
    owned = {str(x).strip().lower() for x in (profile.skills or []) if str(x).strip()}
    wanted = {str(x).strip().lower() for x in requested if str(x).strip()}
    if not wanted:
        return True
    return bool(owned & wanted)


def _candidate_slots(business: Business, *, required_skills: list[str], duration_minutes: int, days: int = 7):
    profiles = list(
        WorkforceProfile.objects.select_related("member", "member__user")
        .filter(member__business=business, member__is_active=True, is_schedulable=True)
    )
    matching = [p for p in profiles if _skill_match(p, required_skills)]
    if not matching:
        matching = profiles if not required_skills else []
    if not matching:
        return [], 0

    now = timezone.localtime()
    slots = []
    for offset in range(days):
        day = (now + timedelta(days=offset)).date()
        day_name = day.strftime("%A").lower()
        for wf in matching:
            bounds = _day_config(wf, day_name)
            if not bounds:
                continue
            start_t, end_t = bounds
            cursor = timezone.make_aware(datetime.combine(day, start_t), timezone.get_current_timezone())
            day_end = timezone.make_aware(datetime.combine(day, end_t), timezone.get_current_timezone())
            if cursor < now:
                minute = ((now.minute + 14) // 15) * 15
                bumped = now.replace(second=0, microsecond=0)
                if minute >= 60:
                    bumped = bumped.replace(minute=0) + timedelta(hours=1)
                else:
                    bumped = bumped.replace(minute=minute)
                cursor = max(cursor, bumped)

            duration = max(15, int(duration_minutes or wf.default_job_duration_minutes or 60))
            buffer_minutes = int(wf.default_buffer_minutes or 0)
            while cursor + timedelta(minutes=duration) <= day_end:
                end = cursor + timedelta(minutes=duration)
                conflict = TicketOperationalProfile.objects.filter(
                    ticket__assigned_business=business,
                    ticket__assigned_member=wf.member.user,
                    ticket__status__in=ACTIVE_TICKET_STATUSES,
                    scheduled_start__lt=end,
                    scheduled_end__gt=cursor,
                ).exists()
                on_time_off = False
                for block in wf.time_off or []:
                    if isinstance(block, dict) and str(block.get("date") or "") == day.isoformat():
                        on_time_off = True
                        break
                if not conflict and not on_time_off:
                    slots.append({
                        "start": cursor.isoformat(),
                        "end": end.isoformat(),
                        "member_id": wf.member_id,
                        "staff_name": wf.member.user.get_full_name() or wf.member.user.email,
                        "title": wf.title or wf.member.get_role_display(),
                    })
                    if len(slots) >= 8:
                        return slots, len(matching)
                cursor = end + timedelta(minutes=buffer_minutes)
    return slots, len(matching)


class MarketplaceAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        category_id = request.query_params.get("category_id")
        zip_code = (request.query_params.get("zip_code") or "").strip()
        duration = max(15, int(request.query_params.get("duration_minutes") or 60))
        skill_query = (request.query_params.get("skills") or "").strip()
        skills = [x.strip() for x in skill_query.split(",") if x.strip()]

        category = None
        if category_id:
            category = ServiceCategory.objects.filter(id=category_id).first()
            if not category:
                return Response({"detail": "Service category not found."}, status=404)
            if not skills:
                skills = [category.name]

        businesses = Business.objects.filter(is_active=True, accepts_marketplace_tickets=True)
        if category:
            businesses = businesses.filter(
                Q(services_offered=category)
                | Q(detailed_services_enabled=False, services_offered__parent=category)
            ).distinct()
        if zip_code:
            businesses = businesses.filter(Q(base_zip=zip_code) | Q(service_areas__icontains=zip_code))

        results = []
        for business in businesses[:50]:
            slots, matching_count = _candidate_slots(
                business,
                required_skills=skills,
                duration_minutes=duration,
            )
            if not slots:
                continue
            results.append({
                "business_id": business.id,
                "name": business.name,
                "phone": business.phone,
                "city": business.city,
                "state": business.state,
                "base_zip": business.base_zip,
                "service_radius_miles": business.effective_service_radius_miles(),
                "matching_staff_count": matching_count,
                "earliest_start": slots[0]["start"],
                "slots": slots[:5],
                "availability_basis": "Configured workforce availability minus scheduled SyncWorks work.",
            })

        results.sort(key=lambda item: item.get("earliest_start") or "9999")
        return Response({
            "results": results,
            "count": len(results),
            "category": {"id": category.id, "name": category.name} if category else None,
            "zip_code": zip_code,
            "duration_minutes": duration,
        })


class MarketplaceBookView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        data = request.data or {}
        business = Business.objects.filter(
            id=data.get("business_id"), is_active=True, accepts_marketplace_tickets=True
        ).first()
        if not business:
            return Response({"detail": "Business is unavailable for Marketplace requests."}, status=404)

        category = None
        if data.get("category_id"):
            category = ServiceCategory.objects.filter(id=data.get("category_id")).first()
            if not category:
                return Response({"detail": "Service category not found."}, status=404)

        try:
            start = datetime.fromisoformat(str(data.get("start")).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(data.get("end")).replace("Z", "+00:00"))
            if timezone.is_naive(start):
                start = timezone.make_aware(start, timezone.get_current_timezone())
            if timezone.is_naive(end):
                end = timezone.make_aware(end, timezone.get_current_timezone())
        except Exception:
            return Response({"detail": "A valid start and end time are required."}, status=400)
        if end <= start or start <= timezone.now():
            return Response({"detail": "Choose a future availability window."}, status=400)

        member = BusinessMember.objects.filter(
            id=data.get("member_id"), business=business, is_active=True
        ).select_related("user").first()
        if not member:
            return Response({"detail": "The selected staff opening is no longer available."}, status=409)

        conflict = TicketOperationalProfile.objects.select_for_update().filter(
            ticket__assigned_business=business,
            ticket__assigned_member=member.user,
            ticket__status__in=ACTIVE_TICKET_STATUSES,
            scheduled_start__lt=end,
            scheduled_end__gt=start,
        ).exists()
        if conflict:
            return Response({"detail": "That opening was just taken. Please choose another time."}, status=409)

        priority = str(data.get("priority") or "STANDARD").upper()
        if priority not in dict(TicketOperationalProfile.Priority.choices):
            priority = TicketOperationalProfile.Priority.STANDARD
        sla = PRIORITY_SLA[priority]
        description = str(data.get("description") or "").strip()
        title = str(data.get("title") or (category.name if category else "Marketplace request")).strip()[:160]
        address = str(data.get("address") or "").strip()
        zip_code = str(data.get("zip_code") or "").strip()

        service_request = ServiceRequest.objects.create(
            customer=request.user,
            category=category,
            title=title,
            description=description,
            priority=priority,
            preferred_time_window=f"{timezone.localtime(start).strftime('%b %d %I:%M %p')} - {timezone.localtime(end).strftime('%I:%M %p')}",
            address=address,
            zip_code=zip_code,
            target_business=business,
            status=ServiceRequest.Status.MATCHED,
            intake_payload={"source": "SYNCWORKS_MARKETPLACE", "business_id": business.id},
        )
        ticket = Ticket.objects.create(
            service_request=service_request,
            customer=request.user,
            category=category,
            assigned_business=business,
            assigned_member=member.user,
            is_marketplace=True,
            service_zip=zip_code,
            service_address=address,
            status=Ticket.Status.SCHEDULED,
            assigned_at=timezone.now(),
            scheduled_at=start,
        )
        ops = TicketOperationalProfile.objects.create(
            ticket=ticket,
            origin=TicketOperationalProfile.Origin.MARKETPLACE,
            priority=priority,
            estimated_duration_minutes=max(15, int((end - start).total_seconds() // 60)),
            duration_low_minutes=max(15, int((end - start).total_seconds() // 60) - 15),
            duration_high_minutes=int((end - start).total_seconds() // 60) + 30,
            required_skills=[category.name] if category else [],
            response_sla_minutes=sla["response"],
            assignment_sla_minutes=sla["assignment"],
            arrival_sla_minutes=sla["arrival"],
            completion_sla_minutes=sla["completion"],
            scheduled_start=start,
            scheduled_end=end,
            expected_finish_at=end,
            customer_visible_note="Booked through SyncWorks Marketplace.",
        )

        return Response({
            "ticket_id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "service_request_id": service_request.id,
            "business": {"id": business.id, "name": business.name},
            "staff": {"member_id": member.id, "name": member.user.get_full_name() or member.user.email},
            "scheduled_start": ops.scheduled_start,
            "scheduled_end": ops.scheduled_end,
            "origin": ops.origin,
            "priority": ops.priority,
            "marketplace_fee_policy": "SyncWorks Marketplace-originated work is eligible for the 1% Marketplace platform fee when revenue is collected.",
        }, status=201)
