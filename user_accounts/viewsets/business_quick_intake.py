"""Business phone intake and a minimal owner tech board.

Manual phone callers are BusinessCustomer records, NOT fake registered customers.
Legacy Ticket.customer is required; business owner is the internal placeholder and
customer_visible=False prevents claiming the caller has an online account.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError

from user_accounts.models import (
    AuditLog, Business, BusinessCustomer, BusinessMember, Ticket,
    TicketOperationalProfile, WorkforceProfile,
)
from user_accounts.services.god_mode import is_god_mode
from user_accounts.viewsets.ticket_conversations import _business_context


LEADERS = {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}


def _business_for_actor(request, *, support_business_id=None):
    if support_business_id is not None:
        if not is_god_mode(request.user):
            raise PermissionDenied("Founder support access required.")
        business = Business.objects.filter(pk=support_business_id, is_active=True).first()
        if not business:
            raise ValidationError({"business": "Business not found or inactive."})
        return business, True

    business, member, _ = _business_context(request)
    if business.owner_id == request.user.id:
        return business, False
    allowed = bool(member and member.is_active and (
        str(member.role or "").upper() in LEADERS
        or member.can_assign_tickets or member.can_manage_schedule
    ))
    if not allowed:
        raise PermissionDenied("Owner or dispatch permission required.")
    return business, False


def _digits(raw):
    return re.sub(r"\D+", "", str(raw or ""))[-15:]


def _customer_payload(c):
    return {
        "id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
        "service_address": c.service_address, "unit": c.unit,
        "city": c.city, "state": c.state, "service_zip": c.service_zip,
        "access_notes": c.access_notes,
        "ticket_count": c.ticket_count,
        "completed_ticket_count": c.completed_ticket_count,
        "last_ticket_id": c.last_ticket_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


class QuickIntakeSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    service_address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    state = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    service_zip = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    access_notes = serializers.CharField(required=False, allow_blank=True, default="")
    service_label = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    urgency = serializers.ChoiceField(choices=TicketOperationalProfile.Priority.choices, default="STANDARD")
    required_skills = serializers.ListField(child=serializers.CharField(max_length=80), required=False, default=list, max_length=12)
    assigned_member_id = serializers.IntegerField(required=False, min_value=1, allow_null=True)
    scheduled_start = serializers.DateTimeField(required=False, allow_null=True)
    estimated_duration_minutes = serializers.IntegerField(required=False, min_value=15, max_value=1440, default=60)
    intake_source = serializers.ChoiceField(choices=["PHONE", "WALK_IN", "TEXT", "EMAIL", "OTHER"], default="PHONE")

    def validate(self, attrs):
        if not any((attrs.get(k) or "").strip() for k in ("customer_name", "email", "phone")):
            raise serializers.ValidationError("Provide customer name, email, or phone.")
        if not attrs.get("service_label", "").strip():
            raise serializers.ValidationError({"service_label": "Describe the requested service."})
        start = attrs.get("scheduled_start")
        if start and timezone.is_naive(start):
            attrs["scheduled_start"] = timezone.make_aware(start)
        return attrs


def _resolve_customer(business, data, actor):
    email = str(data.get("email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()
    name = str(data.get("customer_name") or data.get("name") or "").strip()
    customer = None
    if email:
        customer = BusinessCustomer.objects.filter(business=business, email__iexact=email).first()
    if not customer and _digits(phone):
        customer = BusinessCustomer.objects.filter(business=business, normalized_phone=_digits(phone)).first()
    if not customer and name and data.get("service_address"):
        customer = BusinessCustomer.objects.filter(
            business=business, name__iexact=name,
            service_address__iexact=str(data["service_address"]).strip(),
        ).first()
    new = customer is None
    if new:
        customer = BusinessCustomer(business=business, created_by=actor, record_source="MANUAL")
    # Never overwrite an existing customer's contact/address during a new call.
    for field, key in [
        ("name", "customer_name"), ("email", "email"), ("phone", "phone"),
        ("service_address", "service_address"), ("unit", "unit"), ("city", "city"),
        ("state", "state"), ("service_zip", "service_zip"), ("access_notes", "access_notes"),
    ]:
        value = str(data.get(key) or "").strip()
        if value and not getattr(customer, field):
            setattr(customer, field, value)
    customer.updated_by = actor
    customer.save()
    return customer, new


def create_phone_ticket(business, actor, data, *, founder_support=False):
    s = QuickIntakeSerializer(data=data)
    s.is_valid(raise_exception=True)
    v = s.validated_data
    member_user = None
    member = None
    assigned_id = v.get("assigned_member_id")
    if assigned_id:
        member = BusinessMember.objects.filter(
            business=business, is_active=True, user_id=assigned_id,
        ).select_related("user").first()
        if not member:
            raise ValidationError({"assigned_member_id": "Choose a member of this Business team."})
        required = set(x.strip().casefold() for x in v.get("required_skills", []) if x.strip())
        if required:
            profile = WorkforceProfile.objects.filter(member=member, is_schedulable=True).first()
            actual = set(str(x).strip().casefold() for x in (profile.skills if profile else []))
            if not required.issubset(actual):
                raise ValidationError({"assigned_member_id": "Technician does not have the required skills. Leave unassigned for dispatch."})
        member_user = member.user

    with transaction.atomic():
        customer, is_new = _resolve_customer(business, v, actor)
        start = v.get("scheduled_start")
        duration = v.get("estimated_duration_minutes", 60)
        ticket = Ticket.objects.create(
            customer=business.owner, business_customer=customer,
            assigned_business=business, assigned_member=member_user,
            work_title=v["service_label"].strip(), work_scope=v.get("description", ""),
            service_address=v.get("service_address") or customer.service_address,
            service_zip=v.get("service_zip") or customer.service_zip,
            is_marketplace=False, customer_visible=False,
            customer_status_label="Business-entered request; customer access not yet linked",
            status=Ticket.Status.SCHEDULED if start else Ticket.Status.ASSIGNED if member else Ticket.Status.NEW,
            assigned_at=timezone.now() if member else None,
            scheduled_at=timezone.now() if start else None,
            exclude_from_operational_kpis=bool(business.exclude_from_kpis or business.is_demo),
        )
        TicketOperationalProfile.objects.create(
            ticket=ticket, origin=TicketOperationalProfile.Origin.BUSINESS_ADDED,
            priority=v["urgency"],
            required_skills=v.get("required_skills", []),
            estimated_duration_minutes=duration,
            scheduled_start=start, scheduled_end=start + timedelta(minutes=duration) if start else None,
            expected_finish_at=start + timedelta(minutes=duration) if start else None,
            internal_note=f"Source: {v.get('intake_source', 'PHONE')}. Created by user #{actor.pk}.",
        )
        customer.ticket_count += 1
        if not customer.first_service_at:
            customer.first_service_at = timezone.now()
        customer.last_service_at = timezone.now()
        customer.last_ticket = ticket
        customer.last_service_label = ticket.work_title
        customer.save(update_fields=["ticket_count", "first_service_at", "last_service_at", "last_ticket", "last_service_label", "updated_at"])
        AuditLog.objects.create(
            actor=actor, action="business.phone_ticket_created",
            metadata={
                "business_id": business.pk, "customer_id": customer.pk,
                "ticket_id": ticket.pk, "founder_support": founder_support,
                "intake_source": v.get("intake_source"),
            },
        )
        return ticket, customer, is_new


class BusinessQuickIntakeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        business, _ = _business_for_actor(request)
        ticket, customer, created = create_phone_ticket(business, request.user, request.data)
        return Response({
            "ticket_id": ticket.pk, "customer": _customer_payload(customer),
            "customer_created": created, "assigned_member_id": ticket.assigned_member_id,
            "status": ticket.status, "customer_invited": False,
            "detail": "Ticket and shared customer saved. No welcome email was sent.",
        }, status=status.HTTP_201_CREATED)


class BusinessTechBoardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _ = _business_for_actor(request)
        return Response(_build_tech_board(business, request.query_params.get("date")))


def _build_tech_board(business, raw_date):
    day = parse_date(raw_date) if raw_date else timezone.localdate()
    if day is None:
        raise ValidationError({"date": "Use YYYY-MM-DD."})
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end = start + timedelta(days=1)
    profiles = {
        p.member.user_id: p for p in
        WorkforceProfile.objects.filter(member__business=business, member__is_active=True)
        .select_related("member", "member__user")
    }
    active_jobs = list(
        Ticket.objects.filter(assigned_business=business, archived_at__isnull=True)
        .exclude(status__in=[Ticket.Status.CLOSED, Ticket.Status.CANCELLED])
        .select_related("assigned_member", "business_customer", "operations_profile")
        .order_by("-created_at")[:300]
    )
    def job_row(t):
        op = getattr(t, "operations_profile", None)
        return {
            "ticket_id": t.pk, "title": t.work_title or t.ticket_code,
            "status": t.status, "customer": t.business_customer.name if t.business_customer else "",
            "assigned_member_id": t.assigned_member_id,
            "address": t.service_address,
            "priority": op.priority if op else "STANDARD",
            "scheduled_start": op.scheduled_start.isoformat() if op and op.scheduled_start else None,
            "scheduled_end": op.scheduled_end.isoformat() if op and op.scheduled_end else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "required_skills": op.required_skills if op else [],
        }
    team = list(BusinessMember.objects.filter(business=business, is_active=True).select_related("user"))
    rows = []
    for m in team:
        own = [
            t for t in active_jobs if t.assigned_member_id == m.user_id and
            (not getattr(getattr(t, "operations_profile", None), "scheduled_start", None)
             or start <= t.operations_profile.scheduled_start < end)
        ]
        p = profiles.get(m.user_id)
        rows.append({
            "member_id": m.pk, "user_id": m.user_id,
            "name": m.user.get_full_name() or m.user.email,
            "role": m.role, "skills": p.skills if p else [],
            "is_schedulable": p.is_schedulable if p else False,
            "jobs": [job_row(t) for t in sorted(own, key=lambda t: getattr(getattr(t, "operations_profile", None), "scheduled_start", None) or start)],
        })
    backlog = [
        job_row(t) for t in active_jobs if t.assigned_member_id is None
    ]
    return {
        "business_id": business.pk, "business_name": business.name,
        "date": day.isoformat(), "staff": rows, "unassigned": backlog,
        "summary": {
            "active_tickets": len(active_jobs),
            "unassigned": len(backlog),
            "scheduled_today": sum(
                1 for t in active_jobs if
                getattr(getattr(t, "operations_profile", None), "scheduled_start", None)
                and start <= t.operations_profile.scheduled_start < end
            ),
            "working_now": sum(1 for t in active_jobs if t.status == Ticket.Status.IN_PROGRESS),
        },
        "note": "A board for tracking assignments, not automated routing. Completed jobs are excluded from the active queue.",
    }


class FounderBusinessAssistCustomersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, business_id):
        business, _ = _business_for_actor(request, support_business_id=business_id)
        customers = BusinessCustomer.objects.filter(business=business).order_by("-updated_at")[:200]
        AuditLog.objects.create(actor=request.user, action="platform.business_assist_customers_viewed",
                                metadata={"business_id": business.pk})
        return Response({
            "business": {"id": business.pk, "name": business.name},
            "customers": [_customer_payload(c) for c in customers],
            "support_mode": True,
        })


class FounderBusinessAssistQuickIntakeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, business_id):
        business, _ = _business_for_actor(request, support_business_id=business_id)
        ticket, customer, created = create_phone_ticket(business, request.user, request.data, founder_support=True)
        return Response({
            "ticket_id": ticket.pk, "customer": _customer_payload(customer),
            "customer_created": created, "assigned_member_id": ticket.assigned_member_id,
            "status": ticket.status, "customer_invited": False, "support_mode": True,
        }, status=status.HTTP_201_CREATED)


class FounderBusinessAssistTechBoardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, business_id):
        business, _ = _business_for_actor(request, support_business_id=business_id)
        AuditLog.objects.create(actor=request.user, action="platform.business_assist_techboard_viewed",
                                metadata={"business_id": business.pk})
        data = _build_tech_board(business, request.query_params.get("date"))
        data["support_mode"] = True
        return Response(data)
