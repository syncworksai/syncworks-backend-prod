from __future__ import annotations

from datetime import timedelta

from django.db import transaction

from personal_calendar.models import PersonalCalendarEvent


INACTIVE_TICKET_STATUSES = {"CANCELLED", "CLOSED"}


def _schedule(ticket):
    try:
        operations = ticket.operations_profile
    except Exception:
        operations = None
    start = getattr(operations, "scheduled_start", None) or ticket.scheduled_at
    if not start:
        return None, None, operations
    end = getattr(operations, "scheduled_end", None)
    if not end:
        duration = max(15, int(getattr(operations, "estimated_duration_minutes", 60) or 60))
        end = start + timedelta(minutes=duration)
    return start, end, operations


def _title(ticket):
    service = (
        str(getattr(ticket, "work_title", "") or "").strip()
        or str(getattr(getattr(ticket, "category", None), "name", "") or "").strip()
        or "Service appointment"
    )
    business = str(getattr(getattr(ticket, "assigned_business", None), "name", "") or "").strip()
    return f"{service} · {business}" if business else service


@transaction.atomic
def sync_ticket_to_personal_calendar(ticket):
    """Create or update the customer's canonical SyncWorks service calendar block."""
    lookup = {
        "owner_id": ticket.customer_id,
        "source": PersonalCalendarEvent.Source.TICKET,
        "external_calendar_id": "syncworks-services",
        "external_event_id": str(ticket.pk),
    }
    start, end, operations = _schedule(ticket)
    if not start:
        PersonalCalendarEvent.objects.filter(**lookup).update(status=PersonalCalendarEvent.Status.ARCHIVED)
        return None
    status = PersonalCalendarEvent.Status.CANCELLED if ticket.status in INACTIVE_TICKET_STATUSES else PersonalCalendarEvent.Status.ACTIVE
    address = str(ticket.service_address or "").strip()
    member = getattr(ticket, "assigned_member", None)
    metadata = {
        "ticket_id": ticket.pk,
        "ticket_code": ticket.ticket_code,
        "ticket_status": ticket.status,
        "business_id": ticket.assigned_business_id,
        "business_name": str(getattr(getattr(ticket, "assigned_business", None), "name", "") or ""),
        "technician_id": ticket.assigned_member_id,
        "technician_name": str(member.get_full_name() if member and hasattr(member, "get_full_name") else ""),
        "schedule_origin": str(getattr(operations, "origin", "") or ""),
        "schedule_priority": str(getattr(operations, "priority", "") or ""),
        "customer_visible_note": str(getattr(operations, "customer_visible_note", "") or ""),
        "deep_link": f"/tickets/{ticket.pk}",
        "calendar_owner": "SYNCWORKS_SERVICE",
        "fixed": True,
    }
    defaults = {
        "title": _title(ticket),
        "description": str(getattr(ticket, "work_scope", "") or metadata["customer_visible_note"] or ""),
        "start_at": start,
        "end_at": end,
        "all_day": False,
        "location_name": address,
        "address_line1": address,
        "postal_code": str(ticket.service_zip or ""),
        "created_by_sync": True,
        "status": status,
        "metadata": metadata,
    }
    event, _ = PersonalCalendarEvent.objects.update_or_create(defaults=defaults, **lookup)
    return event
