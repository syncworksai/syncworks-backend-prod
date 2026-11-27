"""Private-pilot AI work intake: durable, auditable, read-only recommendations.

This endpoint never changes tickets, sends notifications, invoices, charges,
or auto-enrolls a paid worker. Assignments await explicit review.
"""
from uuid import UUID, uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog, Ticket, WorkforceProfile, TicketOperationalProfile
from .assist_pilot_views import _pilot

CREATED="sync_assist.assignment.created"
REVIEWED="sync_assist.assignment.reviewed"
AUDITED="sync_assist.assignment.qa_receipt"
ROLES={"CHIEF_OF_STAFF","SALES_MANAGER","MARKETING_MANAGER","RESEARCH_ANALYST","FINANCE_MANAGER","BUSINESS_MANAGER","CUSTOMER_SERVICE","PROPERTY_MANAGER","EXECUTIVE_ASSISTANT","TECHNOLOGY_RESEARCH","QUALITY_ASSURANCE"}
KINDS={"TICKET","SUPPORT","TASK","JOB"}
MAX_ITEMS=150

def _accessible_ticket(user,ticket):
    return bool(ticket and (ticket.customer_id==user.id or (
        ticket.assigned_business_id and ticket.assigned_business and
        ticket.assigned_business.owner_id==user.id
    )))

def _candidate_technicians(ticket):
    """Read-only skill/load shortlist, not a verified routing plan or dispatch."""
    if not ticket or not ticket.assigned_business_id or ticket.assigned_member_id:
        return []
    ops=TicketOperationalProfile.objects.filter(ticket=ticket).first()
    skills={str(x).strip().lower() for x in (ops.required_skills or []) if str(x).strip()} if ops else set()
    profiles=list(WorkforceProfile.objects.select_related("member","member__user","technician_group").filter(
        member__business_id=ticket.assigned_business_id,member__is_active=True,is_schedulable=True
    )[:120])
    if not profiles:return []
    ids=[p.member.user_id for p in profiles]
    today=timezone.localdate()
    counts=dict(TicketOperationalProfile.objects.filter(
        ticket__assigned_business_id=ticket.assigned_business_id,
        ticket__assigned_member_id__in=ids,
        scheduled_start__date=today,
    ).exclude(ticket__status__in=["CANCELLED","PAID","CLOSED"]).values_list(
        "ticket__assigned_member_id"
    ).annotate(n=Count("pk")).values_list("ticket__assigned_member_id","n"))
    rows=[]
    for profile in profiles:
        abilities={str(x).strip().lower() for x in (profile.skills or []) if str(x).strip()}
        if skills and not skills.issubset(abilities):continue
        rows.append({
            "member_id":profile.member_id,
            "technician_name":profile.member.user.get_full_name() or profile.member.user.email,
            "crew":profile.technician_group.name if profile.technician_group_id else "",
            "matched_required_skills":sorted(skills),
            "scheduled_jobs_today":counts.get(profile.member.user_id,0),
            "availability":"not_verified",
            "route":"not_calculated",
        })
    return sorted(rows,key=lambda x:(x["scheduled_jobs_today"],x["technician_name"]))[:3]


def _suggest(ticket):
    if not ticket:
        return "Review instructions, priority, and available information before delegating actions."
    status=ticket.status
    if status in {"PAID","CANCELLED","CLOSED"}:
        return "Ticket is no longer active. Check whether follow-up is actually necessary."
    if status in {"COMPLETED","INVOICED"}:
        return "Review invoicing/payment status. Do not charge, send or change payment terms automatically."
    if not ticket.assigned_member_id:
        return "Unassigned job: review technician skills, availability, location and scheduling conflicts before recommending an assignment."
    if status in {"ASSIGNED","ACCEPTED","SCHEDULED"}:
        return "Review assigned technician and scheduled slot. Suggest follow-up if timing or status needs attention."
    if status in {"EN_ROUTE","ON_SITE","IN_PROGRESS"}:
        return "Check progress and flag overdue work for dispatch; avoid changing technician status without confirmation."
    return "Review ticket lifecycle and identify any actions requiring owner or dispatch approval."

def _snapshot(user):
    states={}
    for event in AuditLog.objects.filter(actor=user,action__in=[CREATED,REVIEWED,AUDITED]).order_by("id"):
        data=event.metadata or {}
        key=str(data.get("assignment_id") or "")
        if event.action==CREATED and key:
            states[key]={**data,"state":"AWAITING_REVIEW","created_at":event.created_at.isoformat()}
        elif event.action==AUDITED and key in states:
            states[key]["audit_receipt"]={**data,"recorded_at":event.created_at.isoformat()}
            if states[key]["state"]!="ARCHIVED": states[key]["state"]="AWAITING_REVIEW"
        elif event.action==REVIEWED and key in states:
            states[key]["state"]=data.get("state","AWAITING_REVIEW")
            states[key]["updated_at"]=event.created_at.isoformat()
    return {"assignments":list(reversed(list(states.values())))[:MAX_ITEMS],
            "execution_mode":"BOUNDED_QA_AND_REVIEW",
            "notice":"Suggestions are informational. No auto-dispatch, payment, email or external AI call is performed."}

class SyncAssistAssignmentsView(APIView):
    permission_classes=[IsAuthenticated]

    def get(self,request):
        if not _pilot(request.user):
            return Response({"detail":"Private pilot only."},status=403)
        return Response(_snapshot(request.user))

    def post(self,request):
        if not _pilot(request.user):
            return Response({"detail":"Private pilot only."},status=403)
        role=str(request.data.get("role") or "").upper()
        kind=str(request.data.get("kind") or "").upper()
        description=request.data.get("description")
        if role not in ROLES or kind not in KINDS or not isinstance(description,str) or not 1<=len(description.strip())<=500:
            return Response({"detail":"Provide a supported role, assignment type, and a 1–500 character description."},status=400)
        request_id=request.data.get("request_id")
        try:key=str(UUID(str(request_id)))
        except (TypeError,ValueError,AttributeError):
            return Response({"detail":"A valid request_id UUID is required."},status=400)
        ticket=None
        ticket_id=request.data.get("ticket_id")
        if ticket_id not in (None,""):
            try: ticket=Ticket.objects.select_related("assigned_business").get(pk=int(ticket_id))
            except (ValueError,TypeError,Ticket.DoesNotExist):
                return Response({"detail":"Ticket not found."},status=404)
            if not _accessible_ticket(request.user,ticket):
                return Response({"detail":"Ticket not found."},status=404)
        elif kind in {"TICKET","SUPPORT","JOB"}:
            return Response({"detail":"Select an existing ticket for ticket, support or job requests."},status=400)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            existing=AuditLog.objects.filter(actor=request.user,action=CREATED,metadata__request_id=key).first()
            if existing:
                m=existing.metadata or {}
                if m.get("role")!=role or m.get("kind")!=kind or m.get("ticket_id")!=(ticket.pk if ticket else None):
                    return Response({"detail":"Request ID already used for another assignment."},status=409)
                return Response({"created":False,"assignment":m},status=200)
            if AuditLog.objects.filter(actor=request.user,action=CREATED).count()>=MAX_ITEMS:
                return Response({"detail":"Pilot assignment limit reached."},status=429)
            record={
                "request_id":key,"assignment_id":str(uuid4()),"role":role,"kind":kind,
                "description":description.strip(),"ticket_id":ticket.pk if ticket else None,
                "ticket_status_at_review":ticket.status if ticket else None,
                "suggested_next_action":_suggest(ticket),
                "technician_candidates":_candidate_technicians(ticket) if ticket and ticket.assigned_business_id and ticket.assigned_business.owner_id==request.user.id else [],
                "requires_approval":True,
            }
            AuditLog.objects.create(actor=request.user,action=CREATED,metadata=record)
        return Response({"created":True,"assignment":{**record,"state":"AWAITING_REVIEW"},
                         "notice":"Saved for review. No job status, payment or external message changed."},status=201)

class SyncAssistAssignmentDecisionView(APIView):
    permission_classes=[IsAuthenticated]

    def post(self,request,assignment_id):
        if not _pilot(request.user):
            return Response({"detail":"Private pilot only."},status=403)
        try: key=str(UUID(str(assignment_id)))
        except (ValueError,TypeError,AttributeError):
            return Response({"detail":"Invalid assignment ID."},status=400)
        decision=str(request.data.get("state") or "").upper()
        if decision not in {"ACKNOWLEDGED","ARCHIVED"}:
            return Response({"detail":"Only acknowledgement or archive is supported; execution is not enabled here."},status=400)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            snapshot=_snapshot(request.user)
            item=next((a for a in snapshot["assignments"] if a["assignment_id"]==key),None)
            if not item:return Response({"detail":"Assignment not found."},status=404)
            AuditLog.objects.create(actor=request.user,action=REVIEWED,metadata={"assignment_id":key,"state":decision})
        return Response(_snapshot(request.user))


class SyncAssistEmployeeWorkView(APIView):
    """Read-only owner-scoped queue for one fixed AI employee role.

    Fresh ticket status is resolved on each read; historical assignment
    recommendations are not represented as live dispatch decisions.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, role):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        from .assist_team_views import SLOTS, EXECUTABLE_ROLES
        role = str(role).strip().upper()
        if role not in {item["role"] for item in SLOTS.values()}:
            return Response({"detail": "Unknown AI employee role."}, status=404)
        all_items = _snapshot(request.user)["assignments"]
        assigned = [item for item in all_items if item.get("role") == role]
        pending = 0
        visible = []
        for item in assigned:
            ticket_id = item.get("ticket_id")
            live_ticket = None
            if ticket_id is not None:
                live_ticket = Ticket.objects.select_related("assigned_business").filter(pk=ticket_id).first()
                # If a business changed hands, never disclose live ticket details
                # merely because the old user retained an audit-log assignment.
                if not _accessible_ticket(request.user, live_ticket):
                    continue
            if item.get("state") == "AWAITING_REVIEW":
                pending += 1
            if len(visible) >= 12:
                continue
            old_status = item.get("ticket_status_at_review")
            current_status = live_ticket.status if live_ticket else None
            visible.append({
                "assignment_id": item.get("assignment_id"),
                "kind": item.get("kind"),
                "description": str(item.get("description") or "")[:500],
                "ticket_id": ticket_id,
                "created_at": item.get("created_at"),
                "state": item.get("state"),
                "suggested_next_action": str(item.get("suggested_next_action") or "")[:500],
                "ticket_status": current_status,
                "status_changed_since_review": bool(live_ticket and old_status != current_status),
                "recommendation_is_historical": True,
                "audit_receipt": item.get("audit_receipt"),
            })
        return Response({
            "role": role,
            "pending_count": pending,
            "assignments": visible,
            "internal_worker_available": role in EXECUTABLE_ROLES,
            "execution_mode": "REVIEW_ONLY",
            "notice": "Assignment suggestions are historical review notes, not fresh scheduling or payment instructions. No actions were run.",
        })


def execute_dashboard_audit(user):
    """Read-only audit of owner calendar/task data, not a browser or visual UI test."""
    import re
    from datetime import timedelta
    from personal_calendar.models import PersonalCalendarEvent
    from django.db.models import Count, Q, F
    if not _pilot(user):
        return {"executed":False,"reason":"not_authorized"}
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        item=next((a for a in _snapshot(user)["assignments"]
            if a.get("role")=="QUALITY_ASSURANCE" and a.get("kind")=="TASK"
            and a.get("state") in {"AWAITING_REVIEW","ACKNOWLEDGED"}
            and not a.get("audit_receipt")
            and re.fullmatch(r"audit (?:the )?(?:syncworks )?customer dashboard[.!]?",str(a.get("description","")),re.I)),None)
        if not item:
            return {"executed":False,"reason":"No eligible unaudited customer dashboard assignment."}
        records=PersonalCalendarEvent.objects.filter(owner=user,status="ACTIVE")
        tasks=records.filter(metadata__entity_type="TASK")
        now=timezone.now()
        missing_title=records.filter(Q(title="")|Q(title__isnull=True)).count()
        invalid_duration=records.filter(end_at__lt=F("start_at")).count()
        duplicates=list(records.filter(metadata__sydney_action_key__isnull=False).values("metadata__sydney_action_key").annotate(n=Count("id")).filter(n__gt=1)[:20])
        sports_duplicates=list(records.filter(external_calendar_id="sydney-sports").values("external_event_id").annotate(n=Count("id")).filter(n__gt=1)[:20])
        stale_workouts=tasks.filter(metadata__task_status="OPEN",metadata__sydney_action_key__startswith="health:plan:",start_at__lt=now-timedelta(days=2)).count()
        findings=[
            {"check":"Blank record titles","count":missing_title},
            {"check":"End before start","count":invalid_duration},
            {"check":"Duplicate Sydney action keys (up to 20 groups)","count":len(duplicates)},
            {"check":"Duplicate sports IDs (up to 20 groups)","count":len(sports_duplicates)},
            {"check":"Open workout planning tasks older than two days","count":stale_workouts},
        ]
        receipt={"assignment_id":item["assignment_id"],"receipt_id":str(uuid4()),"scope":"Owner-scoped calendar and task data integrity only","findings":findings,"records_checked":records.count(),"tasks_checked":tasks.count(),"requires_review":True,"browser_tested":False,"external_actions":0,"model_calls":0}
        AuditLog.objects.create(actor=user,action=AUDITED,metadata=receipt)
        return {"executed":True,**receipt}
