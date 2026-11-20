"""Automatic *review-only* Chief of Staff ticket intake for the founder pilot.

Runs after ticket commit; no LLM, email, payment, or dispatch side effects.
Repeated saves and retries cannot create duplicate review assignments.
"""
from uuid import NAMESPACE_URL,uuid4,uuid5
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from user_accounts.models import AuditLog,Ticket
from .assist_pilot_views import _pilot
from .assist_assignment_views import CREATED,MAX_ITEMS,_suggest,_candidate_technicians

def intake_ticket_for_victoria(ticket_id):
    ticket=Ticket.objects.select_related("assigned_business").filter(pk=ticket_id).first()
    if not ticket or not ticket.assigned_business_id or ticket.is_imported:
        return False
    if ticket.status not in {"NEW","ASSIGNED","ACCEPTED","SCHEDULED"}:
        return False
    if ticket.created_at < timezone.now()-timedelta(days=7):
        return False
    if ticket.assigned_business.is_demo:
        return False
    owner=ticket.assigned_business.owner
    if not _pilot(owner) or ticket.status in {"CANCELLED","CLOSED","PAID"}:
        return False
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        existing=AuditLog.objects.filter(actor=owner,action=CREATED,metadata__automatic_ticket_id=ticket.pk).exists()
        if existing or AuditLog.objects.filter(actor=owner,action=CREATED).count()>=MAX_ITEMS:
            return False
        record={
            "request_id":str(uuid5(NAMESPACE_URL,f"syncworks:business:{ticket.assigned_business_id}:ticket:{ticket.pk}:chief-review")),
            "assignment_id":str(uuid4()),"automatic_ticket_id":ticket.pk,
            "role":"CHIEF_OF_STAFF","kind":"TICKET",
            "description":f"Review new business ticket #{ticket.pk}: {str(ticket.work_title or 'service request')[:150]}. Identify any dispatch, scheduling or owner attention required.",
            "ticket_id":ticket.pk,"ticket_status_at_review":ticket.status,
            "suggested_next_action":_suggest(ticket),
            "technician_candidates":_candidate_technicians(ticket) if not ticket.assigned_member_id else [],
            "requires_approval":True,"source":"AUTO_TICKET_INTAKE",
        }
        AuditLog.objects.create(actor=owner,action=CREATED,metadata=record)
    return True
