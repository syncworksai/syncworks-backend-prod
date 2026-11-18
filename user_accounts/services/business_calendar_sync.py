"""Sync scheduled business work to the business owner's SyncWorks calendar.

The Dispatch Board remains the shared team schedule; this makes the same
appointments visible in the owner's unified personal/business calendar.
"""
from datetime import timedelta

from personal_calendar.models import PersonalCalendarEvent

def sync_ticket_to_business_calendar(ticket):
    if not ticket.assigned_business_id:
        return
    business = ticket.assigned_business
    if not business:
        return
    key = {
        "owner_id":business.owner_id,
        "source":PersonalCalendarEvent.Source.SYSTEM,
        "external_calendar_id":"syncworks-business-schedule",
        "external_event_id":f"business-{business.pk}-ticket-{ticket.pk}",
    }
    try:
        ops = ticket.operations_profile
    except Exception:
        ops = None
    start = getattr(ops,"scheduled_start",None)
    if not start:
        PersonalCalendarEvent.objects.filter(**key).update(status="ARCHIVED")
        return
    end = getattr(ops,"scheduled_end",None) or start + timedelta(minutes=ops.estimated_duration_minutes or 60)
    PersonalCalendarEvent.objects.update_or_create(
        **key,
        defaults={
            "title":f"{business.name} · {ticket.work_title or 'Service request'}",
            "start_at":start,"end_at":end,
            "description":f"Business dispatch service ticket #{ticket.pk}",
            "address_line1":(ticket.service_address or "")[:220],
            "location_name":(ticket.service_address or "")[:180],
            "status":"CANCELLED" if ticket.status in {"CANCELLED","CLOSED"} else "ACTIVE",
            "created_by_sync":True,
            "metadata":{"business_id":business.pk,"business_name":business.name,
                        "event_category":"BUSINESS","ticket_id":ticket.pk,
                        "ticket_status":ticket.status,"deep_link":f"/tickets/{ticket.pk}",
                        "technician_id":ticket.assigned_member_id,"fixed":True},
        },
    )
