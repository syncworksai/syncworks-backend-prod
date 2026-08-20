from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, Ticket, TicketOperationalProfile, WorkforceProfile


def _business_for_request(request):
    raw = request.headers.get("X-Business-ID") or request.query_params.get("business_id") or request.data.get("business_id")
    try:
        business_id = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Choose an active business first.")
    business = Business.objects.filter(pk=business_id, is_active=True).first()
    if not business:
        raise LookupError("Business not found.")
    member = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
    if business.owner_id != request.user.id and not member:
        raise PermissionError("You do not have access to this business.")
    return business, member


def _can_manage(member, business, user):
    return business.owner_id == user.id or bool(member and (member.can_manage_team or member.can_manage_schedule or member.can_manage_settings))


def _member_payload(member):
    profile, _ = WorkforceProfile.objects.get_or_create(member=member)
    user = member.user
    return {
        "member_id": member.id,
        "user_id": user.id,
        "name": (user.get_full_name() or user.email or "Team member").strip(),
        "email": user.email,
        "role": member.role,
        "permissions": {
            "manage_team": member.can_manage_team,
            "manage_settings": member.can_manage_settings,
            "view_financials": member.can_view_financials,
            "manage_invoices": member.can_manage_invoices,
            "create_tickets": member.can_create_tickets,
            "assign_tickets": member.can_assign_tickets,
            "close_tickets": member.can_close_tickets,
            "manage_schedule": member.can_manage_schedule,
        },
        "workforce": {
            "title": profile.title,
            "skills": profile.skills or [],
            "weekly_availability": profile.weekly_availability or {},
            "breaks": profile.breaks or [],
            "time_off": profile.time_off or [],
            "default_buffer_minutes": profile.default_buffer_minutes,
            "default_job_duration_minutes": profile.default_job_duration_minutes,
            "route_start_address": profile.route_start_address,
            "is_schedulable": profile.is_schedulable,
            "notes": profile.notes,
        },
    }


class BusinessWorkforceView(APIView):
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
        members = BusinessMember.objects.select_related("user").filter(business=business, is_active=True).order_by("role", "user__email")
        return Response({"business_id": business.id, "business_name": business.name, "members": [_member_payload(row) for row in members]})

    def patch(self, request):
        try:
            business, requester_member = _business_for_request(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage(requester_member, business, request.user):
            return Response({"detail": "Team or schedule management permission required."}, status=403)
        try:
            member_id = int(request.data.get("member_id"))
        except (TypeError, ValueError):
            return Response({"detail": "member_id is required."}, status=400)
        target = BusinessMember.objects.select_related("user").filter(pk=member_id, business=business, is_active=True).first()
        if not target:
            return Response({"detail": "Team member not found."}, status=404)
        profile, _ = WorkforceProfile.objects.get_or_create(member=target)
        for field in ("title", "route_start_address", "notes"):
            if field in request.data:
                setattr(profile, field, str(request.data.get(field) or "").strip()[:255])
        for field in ("skills", "breaks", "time_off"):
            value = request.data.get(field)
            if field in request.data and isinstance(value, list):
                setattr(profile, field, value[:100])
        if "weekly_availability" in request.data and isinstance(request.data.get("weekly_availability"), dict):
            profile.weekly_availability = request.data.get("weekly_availability")
        for field in ("default_buffer_minutes", "default_job_duration_minutes"):
            if field in request.data:
                try:
                    setattr(profile, field, max(0, min(int(request.data.get(field) or 0), 10080)))
                except (TypeError, ValueError):
                    pass
        if "is_schedulable" in request.data:
            profile.is_schedulable = bool(request.data.get("is_schedulable"))
        profile.save()
        return Response(_member_payload(target))


class TicketOperationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id: int):
        ticket = Ticket.objects.select_related("assigned_business").filter(pk=ticket_id).first()
        if not ticket or not ticket.assigned_business_id:
            return Response({"detail": "Ticket not found."}, status=404)
        business = ticket.assigned_business
        member = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
        if business.owner_id != request.user.id and not member:
            return Response({"detail": "You do not have access to this ticket."}, status=403)
        ops, _ = TicketOperationalProfile.objects.get_or_create(
            ticket=ticket,
            defaults={"origin": "MARKETPLACE" if ticket.is_marketplace else "BUSINESS_ADDED"},
        )
        return Response(self._payload(ops))

    def patch(self, request, ticket_id: int):
        ticket = Ticket.objects.select_related("assigned_business").filter(pk=ticket_id).first()
        if not ticket or not ticket.assigned_business_id:
            return Response({"detail": "Ticket not found."}, status=404)
        business = ticket.assigned_business
        member = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
        if business.owner_id != request.user.id and not (member and (member.can_assign_tickets or member.can_manage_schedule or member.can_manage_settings)):
            return Response({"detail": "Schedule or ticket assignment permission required."}, status=403)
        ops, _ = TicketOperationalProfile.objects.get_or_create(
            ticket=ticket,
            defaults={"origin": "MARKETPLACE" if ticket.is_marketplace else "BUSINESS_ADDED"},
        )
        for field in ("origin", "priority", "customer_visible_note", "internal_note"):
            if field in request.data:
                setattr(ops, field, request.data.get(field))
        for field in ("estimated_duration_minutes", "duration_low_minutes", "duration_high_minutes", "required_staff_count", "response_sla_minutes", "assignment_sla_minutes", "arrival_sla_minutes", "completion_sla_minutes"):
            if field in request.data:
                try:
                    setattr(ops, field, max(0, int(request.data.get(field) or 0)))
                except (TypeError, ValueError):
                    pass
        if "required_skills" in request.data and isinstance(request.data.get("required_skills"), list):
            ops.required_skills = request.data.get("required_skills")[:100]
        ops.save()
        return Response(self._payload(ops))

    @staticmethod
    def _payload(ops):
        return {
            "ticket_id": ops.ticket_id,
            "origin": ops.origin,
            "priority": ops.priority,
            "estimated_duration_minutes": ops.estimated_duration_minutes,
            "duration_low_minutes": ops.duration_low_minutes,
            "duration_high_minutes": ops.duration_high_minutes,
            "required_skills": ops.required_skills or [],
            "required_staff_count": ops.required_staff_count,
            "response_sla_minutes": ops.response_sla_minutes,
            "assignment_sla_minutes": ops.assignment_sla_minutes,
            "arrival_sla_minutes": ops.arrival_sla_minutes,
            "completion_sla_minutes": ops.completion_sla_minutes,
            "expected_finish_at": ops.expected_finish_at.isoformat() if ops.expected_finish_at else None,
            "due_at": ops.due_at.isoformat() if ops.due_at else None,
            "customer_visible_note": ops.customer_visible_note,
            "internal_note": ops.internal_note,
        }


class BusinessOperationsSummaryView(APIView):
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
        members = BusinessMember.objects.filter(business=business, is_active=True)
        open_tickets = Ticket.objects.filter(assigned_business=business).exclude(status__in=["COMPLETED", "PAID", "CLOSED", "CANCELLED"])
        now = timezone.now()
        late = TicketOperationalProfile.objects.filter(ticket__assigned_business=business, due_at__lt=now).exclude(ticket__status__in=["COMPLETED", "PAID", "CLOSED", "CANCELLED"]).count()
        return Response({
            "business_id": business.id,
            "team_total": members.count(),
            "roles": {role: members.filter(role=role).count() for role in ["OWNER", "MANAGER", "DISPATCH", "ACCOUNTING", "TECHNICIAN", "TECH"]},
            "schedulable": WorkforceProfile.objects.filter(member__business=business, member__is_active=True, is_schedulable=True).count(),
            "open_work": open_tickets.count(),
            "sla_late": late,
        })
