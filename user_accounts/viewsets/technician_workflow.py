"""Permission-scoped technician operations: statuses, release and approved job pickup.

No extra database table is required: pickup requests are durable Notification
rows addressed to business dispatch managers, with an explicit approval step.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import BusinessMember, Notification, Ticket, TicketOperationalProfile

logger = logging.getLogger(__name__)
STATUS_TIMESTAMPS = {
    "SCHEDULED": "scheduled_at", "EN_ROUTE": "en_route_at",
    "ON_SITE": "on_site_at", "IN_PROGRESS": "started_at",
    "COMPLETED": "completed_at", "CANCELLED": "cancelled_at",
}
FIELD_STATUSES = {"EN_ROUTE", "ON_SITE", "IN_PROGRESS", "COMPLETED"}
DISPATCH_STATUSES = set(STATUS_TIMESTAMPS) | {"ASSIGNED"}
FINAL = {"CANCELLED", "CLOSED", "PAID", "COMPLETED", "INVOICED"}
PICKUP_TAG = "TECH_JOB_PICKUP_REQUEST"


def _context(request):
    raw = request.headers.get("X-Business-Id") or request.query_params.get("business_id")
    try:
        business_id = int(raw)
    except (ValueError, TypeError):
        return None, None
    from user_accounts.models import Business
    business = Business.objects.filter(pk=business_id, is_active=True).first()
    if not business:
        return None, None
    membership = BusinessMember.objects.filter(
        business=business, user=request.user, is_active=True
    ).first()
    if business.owner_id != request.user.id and not membership:
        return None, None
    return business, membership


def _dispatcher(user, business, member):
    return user.id == business.owner_id or bool(
        member and (member.can_assign_tickets or member.can_manage_schedule)
    )


def _dispatch_recipients(business):
    ids = {business.owner_id}
    ids.update(BusinessMember.objects.filter(
        business=business, is_active=True, can_assign_tickets=True
    ).values_list("user_id", flat=True))
    return ids


def _notify_dispatch(business, actor, ticket, message, *, request_id=None):
    for user_id in _dispatch_recipients(business):
        Notification.objects.create(
            recipient_id=user_id, actor=actor, type=Notification.TYPE_TICKET,
            title="Dispatch attention required",
            body=message[:1000],
            data={"source":"BUSINESS_DISPATCH","business_id":business.id,
                  "ticket_id":ticket.id,"target_path":"/sbo/tech-board",
                  "pickup_request_id":request_id},
        )


def _sync_tech_calendar(ticket, prior_user_id=None):
    """Keep the technician's own SyncWorks personal calendar in sync."""
    from personal_calendar.models import PersonalCalendarEvent
    event_id = f"assigned-work-{ticket.pk}"
    if prior_user_id and prior_user_id != ticket.assigned_member_id:
        PersonalCalendarEvent.objects.filter(
            owner_id=prior_user_id, source="TICKET", external_calendar_id="syncworks-assignments",
            external_event_id=event_id,
        ).update(status="CANCELLED")
    if not ticket.assigned_member_id:
        return
    ops = TicketOperationalProfile.objects.filter(ticket=ticket).first()
    if not ops or not ops.scheduled_start:
        return
    end = ops.scheduled_end or ops.scheduled_start + timedelta(minutes=ops.estimated_duration_minutes or 60)
    PersonalCalendarEvent.objects.update_or_create(
        owner_id=ticket.assigned_member_id, source="TICKET",
        external_calendar_id="syncworks-assignments", external_event_id=event_id,
        defaults={
            "title": f"Assigned job: {(ticket.work_title or 'Service request')[:150]}",
            "description": f"SyncWorks technician assignment #{ticket.pk}",
            "start_at":ops.scheduled_start, "end_at":end,
            "address_line1":(ticket.service_address or "")[:220],
            "status":"CANCELLED" if ticket.status in FINAL else "ACTIVE",
            "metadata":{"ticket_id":ticket.pk,"business_id":ticket.assigned_business_id,
                        "assignment_role":"TECHNICIAN","status":ticket.status},
        },
    )


def _travel_arrival_text(ticket):
    """Conservative travel notice from configured route origin, never fake live GPS."""
    if not ticket.assigned_member_id or not ticket.service_address:
        return ""
    from user_accounts.models import WorkforceProfile
    member = BusinessMember.objects.filter(
        business_id=ticket.assigned_business_id,user_id=ticket.assigned_member_id,
        is_active=True
    ).first()
    profile = WorkforceProfile.objects.filter(member=member).first() if member else None
    origin = (profile.route_start_address or "").strip() if profile else ""
    if not origin:
        return ""
    try:
        from sync_ai.live_operations_views import live_travel
        result = live_travel(origin,ticket.service_address)
        if result.get("basis") == "same_or_missing_location":
            return ""
        raw = result.get("minutes")
        if raw is None or float(raw) <= 0:
            return ""
        from math import ceil
        estimated = int(ceil(float(raw)/10.0)*10)
        arrival = timezone.localtime(timezone.now()+timedelta(minutes=estimated))
        source = "traffic-aware" if result.get("basis") == "google_live_traffic" else "route-estimated"
        return (f" Approximate arrival is {estimated} minutes from the configured "
                f"technician route origin (around {arrival.strftime('%I:%M %p')}). "
                f"This is a {source} estimate, not a live GPS location; traffic and prior stops may change it.")
    except Exception:
        logger.exception("Travel ETA unavailable for ticket=%s",ticket.pk)
        return ""


def _customer_update(ticket, actor, description):
    customer = getattr(ticket, "business_customer", None)
    email = (getattr(customer, "email", "") or "").strip()
    # Phone-entered tickets use the owner as a legacy customer placeholder.
    # Never send a customer inbox notification to that placeholder.
    linked = bool(ticket.customer_visible and ticket.customer_id
                  and ticket.customer_id != ticket.assigned_business.owner_id)
    linked_customer_id = ticket.customer_id if linked else None
    if linked:
        # The linked account is authoritative, never send a linked ticket
        # notification using a potentially different CRM contact email.
        email = (ticket.customer.email or "").strip()
    elif email:
        # A legacy phone ticket may have a CRM contact but no customer link.
        # Notify only a uniquely matched, verified customer account. Do not
        # give that account access to the ticket's private detail URL.
        from django.contrib.auth import get_user_model
        matches = list(get_user_model().objects.filter(
            email__iexact=email, email_verified=True, is_active=True, role="CUSTOMER"
        ).exclude(pk=ticket.assigned_business.owner_id).values_list("id",flat=True)[:2])
        if len(matches) == 1:
            linked_customer_id = matches[0]
    if linked_customer_id:
        Notification.objects.create(
            recipient_id=linked_customer_id, actor=actor, type=Notification.TYPE_TICKET,
            title="Service request updated",
            body=f"{ticket.work_title or 'Service request'}: {description}",
            data={"source":"TICKET","ticket_id":ticket.pk if linked else None,
                  "business_id":ticket.assigned_business_id,
                  "target_path":f"/customer/tickets/{ticket.pk}" if linked else "/customer"},
        )
    if not email or "@" not in email:
        return
    subject = f"SyncWorks service update — ticket #{ticket.pk}"
    body = f"Your service request ({ticket.work_title or 'Service request'}) has been updated.\n\n{description}\n\nPlease contact the service business for questions."
    def deliver():
        try:
            sent = send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email], fail_silently=False)
            if not sent:
                logger.warning("Ticket status email not delivered, ticket=%s", ticket.pk)
        except Exception:
            logger.exception("Ticket status email failed, ticket=%s", ticket.pk)
    transaction.on_commit(deliver)


class TechnicianTicketActionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ticket_id):
        business, member = _context(request)
        if not business:
            return Response({"detail":"Active business membership required."}, status=403)
        ticket = Ticket.objects.select_for_update().select_related(
            "assigned_business", "business_customer", "customer"
        ).filter(pk=ticket_id, assigned_business=business).first()
        if not ticket:
            return Response({"detail":"Ticket not found in selected business."}, status=404)
        action = str(request.data.get("action") or "").strip().upper()
        reason = str(request.data.get("note") or "").strip()[:600]
        dispatch = _dispatcher(request.user, business, member)
        assigned = bool(member and ticket.assigned_member_id == request.user.id)
        if not (dispatch or assigned):
            return Response({"detail":"Only assigned technician or authorized dispatcher may update this job."}, status=403)
        if action == "RELEASE":
            if not reason:
                return Response({"detail":"Explain why this job needs reassignment."}, status=400)
            if ticket.status in FINAL:
                return Response({"detail":"A completed or cancelled job cannot be released."}, status=409)
            previous = ticket.assigned_member_id
            ops = TicketOperationalProfile.objects.select_for_update().filter(ticket=ticket).first()
            if ops and ops.actual_started_at and not ops.actual_finished_at:
                ops.actual_finished_at = timezone.now()
                ops.actual_work_seconds = max(0,int((ops.actual_finished_at - ops.actual_started_at).total_seconds()))
                ops.save(update_fields=["actual_finished_at","actual_work_seconds","updated_at"])
            ticket.assigned_member = None
            ticket.status = Ticket.Status.NEW
            ticket.save(update_fields=["assigned_member", "status"])
            Notification.objects.filter(
                data__source=PICKUP_TAG, data__ticket_id=ticket.id, is_read=False
            ).update(is_read=True, read_at=timezone.now())
            _notify_dispatch(business, request.user, ticket, f"Job #{ticket.pk} returned to queue: {reason}")
            _sync_tech_calendar(ticket, previous)
            _customer_update(ticket, request.user, "A new technician is being arranged.")
            return Response({"ticket_id":ticket.pk,"status":ticket.status,"assigned_member_id":None,"queue":True})
        if action == "DELAYED":
            if not reason:
                return Response({"detail":"Provide a delay reason."},status=400)
            try:
                minutes = min(480,max(5,int(request.data.get("minutes") or 15)))
            except (ValueError,TypeError):
                return Response({"detail":"Delay minutes must be a number."},status=400)
            ops,_ = TicketOperationalProfile.objects.select_for_update().get_or_create(ticket=ticket)
            if ops.expected_finish_at:
                ops.expected_finish_at += timedelta(minutes=minutes)
            elif ops.scheduled_end:
                ops.expected_finish_at = ops.scheduled_end + timedelta(minutes=minutes)
            ops.save(update_fields=["expected_finish_at","updated_at"])
            _notify_dispatch(business,request.user,ticket,f"Job #{ticket.pk} delayed {minutes}m: {reason}")
            _customer_update(ticket,request.user,f"Technician delayed approximately {minutes} minutes. {reason}")
            return Response({"ticket_id":ticket.pk,"status":ticket.status,"delay_minutes":minutes})
        if action not in DISPATCH_STATUSES or (not dispatch and action not in FIELD_STATUSES):
            return Response({"detail":"This status requires dispatch permission."}, status=403)
        if ticket.status in FINAL and action != ticket.status:
            return Response({"detail":"This ticket is already finalized."}, status=409)
        if action == "COMPLETED" and not reason:
            return Response({"detail":"Add a completion summary."}, status=400)
        if action == "CANCELLED" and not reason:
            return Response({"detail":"Cancellation reason is required."}, status=400)
        if action == "SCHEDULED":
            raw_start = str(request.data.get("scheduled_start") or "").strip()
            scheduled = parse_datetime(raw_start) if raw_start else None
            if not scheduled:
                return Response({"detail":"Scheduled start time is required."},status=400)
            if timezone.is_naive(scheduled):
                scheduled = timezone.make_aware(scheduled, timezone.get_current_timezone())
            try:
                duration = int(request.data.get("duration_minutes") or 60)
            except (ValueError,TypeError):
                return Response({"detail":"Duration must be minutes."},status=400)
            if duration < 15 or duration > 1440:
                return Response({"detail":"Duration must be 15–1440 minutes."},status=400)
            ops,_ = TicketOperationalProfile.objects.select_for_update().get_or_create(ticket=ticket)
            ops.scheduled_start = scheduled
            ops.scheduled_end = scheduled + timedelta(minutes=duration)
            ops.expected_finish_at = ops.scheduled_end
            ops.estimated_duration_minutes = duration
            ops.save(update_fields=["scheduled_start","scheduled_end","expected_finish_at","estimated_duration_minutes","updated_at"])
        before = ticket.status
        ticket.status = action
        updates = ["status"]
        stamped = STATUS_TIMESTAMPS.get(action)
        if stamped and getattr(ticket, stamped, None) is None:
            setattr(ticket, stamped, timezone.now())
            updates.append(stamped)
        ticket.save(update_fields=updates)
        if action in {"IN_PROGRESS","COMPLETED","CANCELLED"}:
            ops,_ = TicketOperationalProfile.objects.select_for_update().get_or_create(ticket=ticket)
            if action == "IN_PROGRESS" and not ops.actual_started_at:
                ops.actual_started_at = timezone.now()
                ops.actual_finished_at = None
                ops.save(update_fields=["actual_started_at","actual_finished_at","updated_at"])
            elif action in {"COMPLETED","CANCELLED"} and ops.actual_started_at and not ops.actual_finished_at:
                ops.actual_finished_at = timezone.now()
                ops.actual_work_seconds = max(0,int((ops.actual_finished_at - ops.actual_started_at).total_seconds()))
                ops.save(update_fields=["actual_finished_at","actual_work_seconds","updated_at"])
        _notify_dispatch(business, request.user, ticket,
            f"Job #{ticket.pk}: {before} → {action}." + (f" {reason}" if reason else ""))
        _sync_tech_calendar(ticket)
        eta_note = _travel_arrival_text(ticket) if action == "EN_ROUTE" else ""
        _customer_update(ticket, request.user, f"Status: {action.replace('_',' ').title()}" + (f". {reason}" if reason and action not in {"CANCELLED"} else "") + eta_note)
        return Response({"ticket_id":ticket.pk,"status":ticket.status,"assigned_member_id":ticket.assigned_member_id, "arrival_estimate":eta_note.strip() if action=="EN_ROUTE" else None})


class TechnicianPickupView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ticket_id):
        business, member = _context(request)
        if not business or not member:
            return Response({"detail":"Employee membership required."}, status=403)
        ticket = Ticket.objects.select_for_update().filter(
            pk=ticket_id, assigned_business=business
        ).first()
        if not ticket or ticket.status in FINAL:
            return Response({"detail":"Job unavailable."}, status=404)
        if ticket.assigned_member_id == request.user.id:
            return Response({"detail":"Already assigned to you."}, status=409)
        existing_clock = TicketOperationalProfile.objects.filter(ticket=ticket).first()
        if existing_clock and existing_clock.actual_started_at and not existing_clock.actual_finished_at:
            return Response({"detail":"This job has an active work clock. The assigned technician must release it before pickup."},status=409)
        # A pickup is only a REQUEST. Dispatch must approve.
        from user_accounts.models import WorkforceProfile
        required = set(x.lower() for x in (
            getattr(TicketOperationalProfile.objects.filter(ticket=ticket).first(), "required_skills", []) or []
        ))
        workforce = WorkforceProfile.objects.filter(member=member, is_schedulable=True).first()
        skills = set(x.lower() for x in (workforce.skills if workforce else []))
        if required and not required.issubset(skills):
            return Response({"detail":"Your recorded specialties do not match this job."}, status=403)
        existing = Notification.objects.filter(
            data__source=PICKUP_TAG, data__ticket_id=ticket.id,
            data__requester_id=request.user.id, is_read=False
        ).first()
        if existing:
            return Response({"detail":"Pickup request already pending.","request_id":existing.pk})
        owner_notice = Notification.objects.create(
            recipient_id=business.owner_id, actor=request.user, type=Notification.TYPE_TICKET,
            title="Technician pickup approval required",
            body=f"{request.user.get_full_name() or request.user.email} requests job #{ticket.pk}.",
            data={"source":PICKUP_TAG,"business_id":business.id,"ticket_id":ticket.pk,
                  "requester_id":request.user.id,"assigned_member_id":ticket.assigned_member_id,
                  "target_path":"/sbo/tech-board"},
        )
        for user_id in _dispatch_recipients(business) - {business.owner_id}:
            Notification.objects.create(recipient_id=user_id,actor=request.user,
                type=Notification.TYPE_TICKET,title=owner_notice.title,body=owner_notice.body,
                data={**owner_notice.data,"primary_request_id":owner_notice.pk})
        return Response({"request_id":owner_notice.pk,"state":"AWAITING_DISPATCH_APPROVAL"},status=201)


class TechnicianPickupDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, notification_id):
        business, member = _context(request)
        if not business or not _dispatcher(request.user,business,member):
            return Response({"detail":"Dispatch approval required."},status=403)
        notice = Notification.objects.select_for_update().filter(
            pk=notification_id, data__source=PICKUP_TAG, data__business_id=business.id,
        ).first()
        if not notice:
            return Response({"detail":"Pickup request not found."},status=404)
        main_id = (notice.data or {}).get("primary_request_id")
        if main_id:
            notice = Notification.objects.select_for_update().filter(
                pk=main_id, data__source=PICKUP_TAG, data__business_id=business.id
            ).first()
        if not notice or notice.is_read:
            return Response({"detail":"Pickup request already handled."},status=409)
        decision = str(request.data.get("decision") or "").upper()
        if decision not in {"APPROVE","DECLINE"}:
            return Response({"detail":"Use APPROVE or DECLINE."},status=400)
        ticket = Ticket.objects.select_for_update().select_related("assigned_business","business_customer","customer").filter(
            pk=notice.data["ticket_id"],assigned_business=business
        ).first()
        if not ticket or ticket.status in FINAL or ticket.assigned_member_id != notice.data.get("assigned_member_id"):
            return Response({"detail":"Job assignment changed; review again."},status=409)
        running_clock = TicketOperationalProfile.objects.filter(ticket=ticket).first()
        if running_clock and running_clock.actual_started_at and not running_clock.actual_finished_at:
            return Response({"detail":"Work clock is active; the current technician must stop/release the job."},status=409)
        user_id = notice.data["requester_id"]
        candidate = BusinessMember.objects.filter(business=business,user_id=user_id,is_active=True).first()
        if not candidate:
            return Response({"detail":"Requesting technician is unavailable."},status=409)
        old_id = ticket.assigned_member_id
        if decision == "APPROVE":
            ticket.assigned_member_id = user_id
            if ticket.status == Ticket.Status.NEW:
                ticket.status = Ticket.Status.ASSIGNED
                ticket.save(update_fields=["assigned_member","status"])
            else:
                ticket.save(update_fields=["assigned_member"])
            _sync_tech_calendar(ticket,old_id)
            _customer_update(ticket,request.user,"Your assigned technician has changed.")
        Notification.objects.filter(
            data__source=PICKUP_TAG, data__ticket_id=ticket.id, is_read=False
        ).update(is_read=True,read_at=timezone.now())
        Notification.objects.create(recipient_id=user_id,actor=request.user,
            type=Notification.TYPE_TICKET,title="Pickup request "+decision.title(),
            body=f"Your pickup request for job #{ticket.id} was {decision.lower()}.",
            data={"source":"TICKET","ticket_id":ticket.id,"target_path":"/employee"})
        return Response({"state":decision,"ticket_id":ticket.id,
                         "assigned_member_id":ticket.assigned_member_id})


class TechnicianTeamBoardView(APIView):
    """Team visibility for members without granting dispatch write permission."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, member = _context(request)
        if not business or not member:
            return Response({"detail":"Active employee membership required."},status=403)
        qs = Ticket.objects.filter(assigned_business=business).exclude(
            status__in=["CLOSED","CANCELLED","PAID","INVOICED"]
        ).select_related("operations_profile").order_by("id")[:300]
        people = BusinessMember.objects.filter(business=business,is_active=True).select_related("user")
        jobs_by_user = {}
        unassigned = []
        for ticket in qs:
            ops = TicketOperationalProfile.objects.filter(ticket=ticket).first()
            row = {
                "ticket_id":ticket.id,"title":ticket.work_title or "Service request",
                "status":ticket.status,
                "scheduled_start":ops.scheduled_start.isoformat() if ops and ops.scheduled_start else None,
                "scheduled_end":ops.scheduled_end.isoformat() if ops and ops.scheduled_end else None,
                "required_skills":ops.required_skills if ops else [],
                "assigned_member_id":ticket.assigned_member_id,
            }
            if ticket.assigned_member_id:
                jobs_by_user.setdefault(ticket.assigned_member_id,[]).append(row)
            else:
                unassigned.append(row)
        from user_accounts.models import WorkforceProfile
        profiles = {p.member_id:p for p in WorkforceProfile.objects.filter(member__business=business)}
        rows = []
        for person in people:
            profile = profiles.get(person.id)
            rows.append({
                "member_id":person.id,"user_id":person.user_id,
                "name":person.user.get_full_name() or person.user.email,
                "role":person.role,"skills":profile.skills if profile else [],
                "technician_group_id":profile.technician_group_id if profile else None,
                "technician_group_name":profile.technician_group.name if profile and profile.technician_group_id else "",
                "jobs":jobs_by_user.get(person.user_id,[]),
                "is_self":person.user_id==request.user.id,
            })
        return Response({"staff":rows,"unassigned":unassigned,
                         "business_id":business.id,"can_dispatch":_dispatcher(request.user,business,member)})


class TechnicianPickupInboxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, member = _context(request)
        if not business or not _dispatcher(request.user,business,member):
            return Response({"detail":"Dispatch permission required."},status=403)
        pending = Notification.objects.filter(
            recipient_id__in=_dispatch_recipients(business),
            data__source=PICKUP_TAG,
            data__business_id=business.id,
            is_read=False,
        ).order_by("id")
        seen=set()
        result=[]
        for notice in pending:
            primary=(notice.data or {}).get("primary_request_id") or notice.id
            if primary in seen:continue
            seen.add(primary)
            result.append({"id":primary,"ticket_id":notice.data.get("ticket_id"),
                           "requester_id":notice.data.get("requester_id"),
                           "title":notice.title,"body":notice.body,
                           "created_at":notice.created_at.isoformat()})
        return Response({"requests":result})
