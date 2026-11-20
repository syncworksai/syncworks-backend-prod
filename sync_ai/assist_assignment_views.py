"""Private-pilot AI work intake: durable, auditable, read-only recommendations.

This endpoint never changes tickets, sends notifications, invoices, charges,
or auto-enrolls a paid worker. Assignments await explicit review.
"""
from uuid import UUID, uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog, Ticket
from .assist_pilot_views import _pilot

CREATED="sync_assist.assignment.created"
REVIEWED="sync_assist.assignment.reviewed"
ROLES={"CHIEF_OF_STAFF","SALES_MANAGER","MARKETING_MANAGER","RESEARCH_ANALYST","FINANCE_MANAGER","BUSINESS_MANAGER","CUSTOMER_SERVICE","PROPERTY_MANAGER","EXECUTIVE_ASSISTANT"}
KINDS={"TICKET","SUPPORT","TASK","JOB"}
MAX_ITEMS=150

def _accessible_ticket(user,ticket):
    return bool(ticket and (ticket.customer_id==user.id or (
        ticket.assigned_business_id and ticket.assigned_business and
        ticket.assigned_business.owner_id==user.id
    )))

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
    for event in AuditLog.objects.filter(actor=user,action__in=[CREATED,REVIEWED]).order_by("id"):
        data=event.metadata or {}
        key=str(data.get("assignment_id") or "")
        if event.action==CREATED and key:
            states[key]={**data,"state":"AWAITING_REVIEW","created_at":event.created_at.isoformat()}
        elif event.action==REVIEWED and key in states:
            states[key]["state"]=data.get("state","AWAITING_REVIEW")
            states[key]["updated_at"]=event.created_at.isoformat()
    return {"assignments":list(reversed(list(states.values())))[:MAX_ITEMS],
            "execution_mode":"REVIEW_ONLY",
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
                "suggested_next_action":_suggest(ticket),"requires_approval":True,
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
