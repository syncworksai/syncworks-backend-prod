# backend/user_accounts/services/ticket_events.py
from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from user_accounts.models import Ticket, TicketViewEvent, Business
from user_accounts.services.tickets import marketplace_tickets_for_business


def _active_business_from_request(request) -> Business | None:
    bid = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not bid:
        return None
    try:
        bid_int = int(bid)
    except Exception:
        return None
    return Business.objects.filter(id=bid_int, is_active=True).first()


def _role(user) -> str:
    return (getattr(user, "role", "") or "").upper()


def record_event(*, ticket: Ticket, actor, business: Business | None, event_type: str) -> TicketViewEvent:
    return TicketViewEvent.objects.create(
        ticket=ticket,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        business=business,
        event_type=event_type,
    )


def mark_viewed(*, request, ticket: Ticket) -> dict:
    user = request.user
    role = _role(user)

    if role == "CUSTOMER":
        if ticket.customer_id != user.id:
            raise PermissionDenied("Not your ticket.")
        record_event(ticket=ticket, actor=user, business=None, event_type=TicketViewEvent.EventType.CUSTOMER_VIEWED)
        return {"ok": True, "event": "CUSTOMER_VIEWED"}

    if role in {"SBO", "EMPLOYEE", "PROPERTY_MGR", "PM"}:
        biz = _active_business_from_request(request)
        if not biz:
            raise ValidationError("Missing X-Business-Id for business view tracking.")

        if ticket.assigned_business_id:
            if ticket.assigned_business_id != biz.id:
                raise PermissionDenied("Ticket not scoped to this business.")
        else:
            if not getattr(ticket, "is_marketplace", False):
                raise PermissionDenied("Ticket is not marketplace and not assigned to your business.")
            eligible_ids = set(marketplace_tickets_for_business(biz).values_list("id", flat=True))
            if ticket.id not in eligible_ids:
                raise PermissionDenied("Ticket not eligible for this business.")

        record_event(ticket=ticket, actor=user, business=biz, event_type=TicketViewEvent.EventType.BUSINESS_VIEWED)
        return {"ok": True, "event": "BUSINESS_VIEWED", "business_id": biz.id}

    record_event(ticket=ticket, actor=user, business=None, event_type=TicketViewEvent.EventType.BUSINESS_VIEWED)
    return {"ok": True, "event": "BUSINESS_VIEWED"}


def decline_marketplace(*, request, ticket: Ticket) -> dict:
    user = request.user
    role = _role(user)
    if role not in {"SBO", "EMPLOYEE", "PROPERTY_MGR", "PM"}:
        raise PermissionDenied("Only providers can decline marketplace tickets.")

    if not getattr(ticket, "is_marketplace", False):
        raise ValidationError("Not a marketplace ticket.")

    if ticket.assigned_business_id is not None:
        raise ValidationError("Ticket is already assigned; cannot decline marketplace.")

    biz = _active_business_from_request(request)
    if not biz:
        raise ValidationError("Missing X-Business-Id for decline tracking.")

    eligible_ids = set(marketplace_tickets_for_business(biz).values_list("id", flat=True))
    if ticket.id not in eligible_ids:
        raise PermissionDenied("Ticket not eligible for this business.")

    # ✅ FIX: use the same event_type your marketplace filter expects
    record_event(ticket=ticket, actor=user, business=biz, event_type=TicketViewEvent.EventType.DECLINED_MARKETPLACE)
    return {"ok": True, "declined": True, "business_id": biz.id}


def _require_assigned_to_active_business(request, ticket: Ticket) -> Business:
    biz = _active_business_from_request(request)
    if not biz:
        raise ValidationError("Missing X-Business-Id.")

    if ticket.assigned_business_id != biz.id:
        raise PermissionDenied("Ticket not assigned to this business.")
    return biz


def provider_schedule(*, request, ticket: Ticket) -> dict:
    _require_assigned_to_active_business(request, ticket)
    ticket.status = Ticket.Status.SCHEDULED
    ticket.scheduled_at = timezone.now()
    ticket.save(update_fields=["status", "scheduled_at"])
    return {"ok": True, "status": ticket.status}


def provider_en_route(*, request, ticket: Ticket) -> dict:
    _require_assigned_to_active_business(request, ticket)
    ticket.status = Ticket.Status.EN_ROUTE
    ticket.en_route_at = timezone.now()
    ticket.save(update_fields=["status", "en_route_at"])
    return {"ok": True, "status": ticket.status}


def provider_on_site(*, request, ticket: Ticket) -> dict:
    _require_assigned_to_active_business(request, ticket)
    ticket.status = Ticket.Status.ON_SITE
    ticket.on_site_at = timezone.now()
    ticket.save(update_fields=["status", "on_site_at"])
    return {"ok": True, "status": ticket.status}


def provider_awaiting_approval(*, request, ticket: Ticket) -> dict:
    _require_assigned_to_active_business(request, ticket)
    ticket.status = Ticket.Status.AWAITING_APPROVAL
    ticket.awaiting_approval_at = timezone.now()
    ticket.save(update_fields=["status", "awaiting_approval_at"])
    return {"ok": True, "status": ticket.status}
