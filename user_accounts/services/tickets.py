# backend/user_accounts/services/tickets.py
from __future__ import annotations

from dataclasses import dataclass
from math import radians, cos, sin, asin, sqrt
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from user_accounts.models import (
    Ticket,
    ServiceRequest,
    Business,
    BusinessMember,
    TicketMessage,
    Notification,
    TicketViewEvent,
    FavoriteBusiness,
    TicketQuote,
    Invoice,
)

from user_accounts.services.notifications import notify


# ----------------------------
# Geo helpers (ZIP distance)
# ----------------------------

@dataclass
class _LatLon:
    lat: float
    lon: float


def _haversine_miles(a: _LatLon, b: _LatLon) -> float:
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [a.lat, a.lon, b.lat, b.lon])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(h))


def _zip_to_latlon(zip_code: str) -> Optional[_LatLon]:
    z = (zip_code or "").strip()
    if not z:
        return None

    try:
        import pgeocode  # type: ignore
    except Exception:
        return None

    try:
        nomi = pgeocode.Nominatim("us")
        row = nomi.query_postal_code(z)
        lat = getattr(row, "latitude", None)
        lon = getattr(row, "longitude", None)
        if lat is None or lon is None:
            return None
        if str(lat) == "nan" or str(lon) == "nan":
            return None
        return _LatLon(float(lat), float(lon))
    except Exception:
        return None


def _zip_within_radius(zip_a: str, zip_b: str, radius_miles: int) -> bool:
    za = (zip_a or "").strip()
    zb = (zip_b or "").strip()
    if not za or not zb:
        return False

    if za.lower() == zb.lower():
        return True

    a = _zip_to_latlon(za)
    b = _zip_to_latlon(zb)
    if not a or not b:
        return False

    return _haversine_miles(a, b) <= float(radius_miles)


# ----------------------------
# Ticket routing helpers
# ----------------------------

def _ticket_zip(ticket: Ticket) -> str:
    z = (getattr(ticket, "service_zip", "") or "").strip()
    if z:
        return z
    try:
        sr = ticket.service_request
        return (getattr(sr, "zip_code", "") or "").strip()
    except Exception:
        return ""


def _business_radius(business: Business) -> int:
    DEFAULT = 25
    r = getattr(business, "service_radius_miles", None)
    try:
        r = int(r) if r is not None else DEFAULT
    except Exception:
        r = DEFAULT
    if r < 1:
        return 1
    if r > 200:
        return 200
    return r


def _business_can_take_category(business: Business, ticket: Ticket) -> bool:
    if not ticket.category_id:
        return False
    offered_ids = list(business.services_offered.values_list("id", flat=True))
    return ticket.category_id in offered_ids


def is_ticket_eligible_for_business(ticket: Ticket, business: Business) -> bool:
    if not business or not getattr(business, "is_active", False):
        return False

    if ticket.is_marketplace and not getattr(business, "accepts_marketplace_tickets", False):
        return False

    if not _business_can_take_category(business, ticket):
        return False

    base_zip = (getattr(business, "base_zip", "") or "").strip()
    tzip = _ticket_zip(ticket)
    if not base_zip or not tzip:
        return False

    if base_zip.lower() == tzip.lower():
        return True

    radius = _business_radius(business)
    return _zip_within_radius(base_zip, tzip, radius)


def marketplace_tickets_for_business(business: Business):
    qs = Ticket.objects.filter(is_marketplace=True).order_by("-created_at")

    if not business or not getattr(business, "is_active", False):
        return qs.none()

    if not getattr(business, "accepts_marketplace_tickets", False):
        return qs.none()

    offered_ids = list(business.services_offered.values_list("id", flat=True))
    if not offered_ids:
        return qs.none()

    qs = qs.filter(category_id__in=offered_ids)
    qs = qs.filter(assigned_business__isnull=True)

    # ✅ FIX: exclude both decline event types (your codebase uses both)
    declined_ids = TicketViewEvent.objects.filter(
        business_id=business.id,
        event_type__in=[
            TicketViewEvent.EventType.DECLINED_MARKETPLACE,
            TicketViewEvent.EventType.BUSINESS_DECLINED,
        ],
    ).values_list("ticket_id", flat=True)
    qs = qs.exclude(id__in=declined_ids)

    qs = qs.filter(
        Q(service_zip__isnull=False) & ~Q(service_zip="") |
        Q(service_request__zip_code__isnull=False) & ~Q(service_request__zip_code="")
    )

    base_zip = (getattr(business, "base_zip", "") or "").strip()
    if not base_zip:
        return qs.none()

    exact = qs.filter(Q(service_zip__iexact=base_zip) | Q(service_request__zip_code__iexact=base_zip))
    candidates = qs.exclude(Q(service_zip__iexact=base_zip) | Q(service_request__zip_code__iexact=base_zip))

    ids: list[int] = []
    for t in candidates.select_related("service_request").only(
        "id",
        "service_zip",
        "category_id",
        "is_marketplace",
        "service_request__zip_code",
    ):
        if is_ticket_eligible_for_business(t, business):
            ids.append(t.id)

    if ids:
        return (exact | Ticket.objects.filter(id__in=ids)).distinct().order_by("-created_at")

    return exact.distinct().order_by("-created_at")


def ticket_eligible_businesses(ticket: Ticket):
    qs = Business.objects.filter(is_active=True).order_by("name")

    if ticket.category_id:
        qs = qs.filter(services_offered__id=ticket.category_id)

    if ticket.is_marketplace:
        qs = qs.filter(accepts_marketplace_tickets=True)

    tzip = _ticket_zip(ticket)
    if not tzip:
        return Business.objects.none()

    exact = qs.filter(base_zip__iexact=tzip)
    candidates = qs.exclude(base_zip__iexact=tzip).exclude(Q(base_zip__isnull=True) | Q(base_zip=""))

    ids: list[int] = []
    for b in candidates.only("id", "base_zip", "service_radius_miles", "accepts_marketplace_tickets", "is_active"):
        if _zip_within_radius((b.base_zip or ""), tzip, _business_radius(b)):
            ids.append(b.id)

    if ids:
        return (exact | Business.objects.filter(id__in=ids)).distinct().order_by("name")

    return exact.distinct().order_by("name")


# ----------------------------
# Create + state transitions
# ----------------------------

def _coerce_radius(service_radius_miles: Optional[int]) -> int:
    DEFAULT = 25
    if service_radius_miles is None:
        return DEFAULT
    try:
        r = int(service_radius_miles)
    except Exception:
        return DEFAULT
    if r < 1:
        return 1
    if r > 200:
        return 200
    return r


@transaction.atomic
def create_request_and_ticket(
    customer,
    category,
    title: str,
    description: str,
    preferred_sbo_user=None,
    *,
    service_zip: str = "",
    service_radius_miles: Optional[int] = None,
    service_address: str = "",
    is_marketplace: bool = False,
) -> ServiceRequest:
    clean_zip = (service_zip or "").strip()
    clean_addr = (service_address or "").strip()
    clean_radius = _coerce_radius(service_radius_miles)

    sr = ServiceRequest.objects.create(
        customer=customer,
        category=category,
        title=title,
        description=description or "",
        preferred_sbo_user=preferred_sbo_user,
        address=clean_addr,
        zip_code=clean_zip,
    )

    t = Ticket.objects.create(
        service_request=sr,
        customer=customer,
        category=category,
        status=Ticket.Status.NEW,
        is_marketplace=bool(is_marketplace),
        service_zip=clean_zip,
        service_address=clean_addr,
        service_radius_miles=clean_radius,
    )

    TicketMessage.objects.create(
        ticket=t,
        sender=customer,
        body="Ticket created.",
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        customer,
        "Ticket created",
        f"Your ticket #{t.id} was created.",
        {"ticket_id": t.id},
        type=Notification.TYPE_TICKET,
        actor=customer,
    )

    return sr


@transaction.atomic
def assign_ticket_to_business(ticket: Ticket, business: Business, assigned_member: BusinessMember | None = None):
    ticket.assigned_business = business
    ticket.assigned_member = assigned_member.user if assigned_member else None
    ticket.status = Ticket.Status.ASSIGNED
    ticket.is_marketplace = False

    ticket.accepted_at = None
    ticket.started_at = None
    ticket.completed_at = None
    ticket.closed_at = None
    ticket.cancelled_at = None
    ticket.assigned_at = timezone.now()
    ticket.save()

    notify(
        ticket.customer,
        "Ticket assigned",
        f"Your ticket #{ticket.id} was assigned to {business.name}.",
        {"ticket_id": ticket.id, "business_id": business.id},
        type=Notification.TYPE_TICKET,
        actor=business.owner,
    )
    notify(
        business.owner,
        "New assigned ticket",
        f"Ticket #{ticket.id} assigned to your business.",
        {"ticket_id": ticket.id, "business_id": business.id},
        type=Notification.TYPE_TICKET,
        actor=ticket.customer,
    )

    TicketMessage.objects.create(
        ticket=ticket,
        sender=ticket.customer,
        body=f"Assigned to {business.name}.",
        type=TicketMessage.MessageType.SYSTEM,
    )


@transaction.atomic
def send_ticket_to_marketplace(ticket: Ticket):
    z = _ticket_zip(ticket)
    if not z:
        raise ValueError("Ticket must have service_zip (or ServiceRequest.zip_code) before sending to marketplace.")

    ticket.is_marketplace = True
    ticket.status = Ticket.Status.NEW
    ticket.assigned_business = None
    ticket.assigned_member = None

    ticket.accepted_at = None
    ticket.started_at = None
    ticket.completed_at = None
    ticket.closed_at = None
    ticket.cancelled_at = None
    ticket.assigned_at = None
    ticket.save()

    notify(
        ticket.customer,
        "Ticket sent to marketplace",
        f"Ticket #{ticket.id} is now visible to eligible providers.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=ticket.customer,
    )


# ----------------------------
# ✅ NEW: Provider decline + reroute
# ----------------------------

@transaction.atomic
def provider_decline(ticket: Ticket, *, actor_user, business: Business, reason: str = ""):
    """
    Provider declines:
      - If marketplace/unassigned: record decline event only (hide from that business).
      - If assigned to this business: record decline + reroute to marketplace.
    """
    if not business or not getattr(business, "is_active", False):
        raise ValueError("Invalid business.")

    # Marketplace/unassigned decline
    if ticket.is_marketplace and ticket.assigned_business_id is None:
        TicketViewEvent.objects.create(
            ticket=ticket,
            actor=actor_user,
            business=business,
            event_type=TicketViewEvent.EventType.DECLINED_MARKETPLACE,
        )
        body = f"{business.name} declined marketplace ticket."
        if (reason or "").strip():
            body += f" Reason: {reason.strip()}"
        TicketMessage.objects.create(
            ticket=ticket,
            sender=actor_user,
            body=body,
            type=TicketMessage.MessageType.SYSTEM,
        )
        return

    # Assigned decline (must be assigned to THIS business)
    if ticket.assigned_business_id != business.id:
        raise ValueError("Ticket is not assigned to your business.")

    # Record decline event so it won't reappear in marketplace for this business
    TicketViewEvent.objects.create(
        ticket=ticket,
        actor=actor_user,
        business=business,
        event_type=TicketViewEvent.EventType.BUSINESS_DECLINED,
    )
    TicketViewEvent.objects.create(
        ticket=ticket,
        actor=actor_user,
        business=business,
        event_type=TicketViewEvent.EventType.DECLINED_MARKETPLACE,
    )

    body = f"{business.name} declined ticket (rerouted to marketplace)."
    if (reason or "").strip():
        body += f" Reason: {reason.strip()}"
    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body=body,
        type=TicketMessage.MessageType.SYSTEM,
    )

    # reroute
    send_ticket_to_marketplace(ticket)


@transaction.atomic
def provider_accept(ticket: Ticket, actor_user):
    if ticket.status not in (Ticket.Status.NEW, Ticket.Status.ASSIGNED):
        raise ValueError("Ticket cannot be accepted in current status.")

    ticket.status = Ticket.Status.ACCEPTED
    ticket.accepted_at = timezone.now()
    ticket.save()

    notify(
        ticket.customer,
        "Provider accepted",
        f"Your ticket #{ticket.id} was accepted.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Provider accepted the ticket.",
        type=TicketMessage.MessageType.SYSTEM,
    )


@transaction.atomic
def provider_set_needs_quote(ticket: Ticket, actor_user):
    """
    Provider marks the ticket as "Needs Quote" (estimate required before work).
    """
    if ticket.status in (Ticket.Status.CANCELLED, Ticket.Status.CLOSED, Ticket.Status.PAID):
        raise ValueError("Ticket cannot request a quote in this status.")

    ticket.status = Ticket.Status.NEEDS_QUOTE
    ticket.save()

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Provider requested an estimate (Needs Quote).",
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        ticket.customer,
        "Estimate requested",
        f"Ticket #{ticket.id} requires an estimate before work proceeds.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )


@transaction.atomic
def provider_send_quote(ticket: Ticket, quote: TicketQuote, actor_user):
    if quote.ticket_id != ticket.id:
        raise ValueError("Quote does not belong to this ticket.")

    if ticket.status in (Ticket.Status.CANCELLED, Ticket.Status.CLOSED, Ticket.Status.PAID):
        raise ValueError("Ticket cannot be quoted in this status.")

    quote.status = TicketQuote.Status.SENT
    quote.sent_at = timezone.now()
    quote.approved_by = None
    quote.approved_at = None
    quote.rejected_by = None
    quote.rejected_at = None
    quote.save()

    ticket.status = Ticket.Status.QUOTED
    ticket.save()

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body=f"Estimate sent (${quote.amount}).",
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        ticket.customer,
        "Estimate sent",
        f"An estimate for ticket #{ticket.id} is ready for review.",
        {"ticket_id": ticket.id, "quote_id": quote.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )


@transaction.atomic
def customer_approve_quote(ticket: Ticket, quote: TicketQuote, actor_user):
    if quote.ticket_id != ticket.id:
        raise ValueError("Quote does not belong to this ticket.")
    if quote.status != TicketQuote.Status.SENT:
        raise ValueError("Only SENT quotes can be approved.")

    quote.status = TicketQuote.Status.APPROVED
    quote.approved_by = actor_user
    quote.approved_at = timezone.now()
    quote.save()

    ticket.status = Ticket.Status.APPROVED
    ticket.save()

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Customer approved the estimate.",
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        ticket.customer,
        "Estimate approved",
        f"You approved the estimate for ticket #{ticket.id}.",
        {"ticket_id": ticket.id, "quote_id": quote.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )


@transaction.atomic
def customer_reject_quote(ticket: Ticket, quote: TicketQuote, actor_user, reason: str = ""):
    if quote.ticket_id != ticket.id:
        raise ValueError("Quote does not belong to this ticket.")
    if quote.status != TicketQuote.Status.SENT:
        raise ValueError("Only SENT quotes can be rejected.")

    quote.status = TicketQuote.Status.REJECTED
    quote.rejected_by = actor_user
    quote.rejected_at = timezone.now()
    quote.save()

    ticket.status = Ticket.Status.QUOTE_REJECTED
    ticket.save()

    msg = "Customer rejected the estimate."
    if (reason or "").strip():
        msg += f" Reason: {reason.strip()}"

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body=msg,
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        ticket.customer,
        "Estimate rejected",
        f"You rejected the estimate for ticket #{ticket.id}.",
        {"ticket_id": ticket.id, "quote_id": quote.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )


@transaction.atomic
def provider_start(ticket: Ticket, actor_user):
    if ticket.status != Ticket.Status.ACCEPTED:
        raise ValueError("Ticket must be ACCEPTED before starting.")

    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.started_at = timezone.now()
    ticket.save()

    notify(
        ticket.customer,
        "Work started",
        f"Ticket #{ticket.id} is now in progress.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Work started.",
        type=TicketMessage.MessageType.SYSTEM,
    )


@transaction.atomic
def provider_complete(ticket: Ticket, actor_user):
    if ticket.status != Ticket.Status.IN_PROGRESS:
        raise ValueError("Ticket must be IN_PROGRESS before completing.")

    ticket.status = Ticket.Status.COMPLETED
    ticket.completed_at = timezone.now()
    ticket.save()

    try:
        if ticket.customer_id and ticket.assigned_business_id:
            FavoriteBusiness.objects.get_or_create(
                customer_id=ticket.customer_id,
                business_id=ticket.assigned_business_id,
                defaults={"nickname": ""},
            )
    except Exception:
        pass

    notify(
        ticket.customer,
        "Work completed",
        f"Ticket #{ticket.id} marked completed.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Work completed.",
        type=TicketMessage.MessageType.SYSTEM,
    )


def customer_can_cancel_ticket(ticket: Ticket) -> bool:
    if ticket.assigned_business_id is not None:
        return False
    if ticket.status in (Ticket.Status.COMPLETED, Ticket.Status.PAID, Ticket.Status.CLOSED):
        return False
    return True


@transaction.atomic
def cancel_ticket(ticket: Ticket, actor_user, *, actor_is_customer: bool = False):
    if ticket.status in (Ticket.Status.COMPLETED, Ticket.Status.CLOSED, Ticket.Status.PAID):
        raise ValueError("Ticket cannot be cancelled after completion/close/paid.")

    if actor_is_customer and not customer_can_cancel_ticket(ticket):
        raise ValueError("Customer cannot cancel after a provider picks up the ticket.")

    ticket.status = Ticket.Status.CANCELLED
    ticket.cancelled_at = timezone.now()
    ticket.save()

    notify(
        ticket.customer,
        "Ticket cancelled",
        f"Ticket #{ticket.id} cancelled.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Ticket cancelled.",
        type=TicketMessage.MessageType.SYSTEM,
    )


@transaction.atomic
def provider_send_invoice(ticket: Ticket, invoice: Invoice, actor_user):
    if invoice.ticket_id != ticket.id:
        raise ValueError("Invoice does not belong to this ticket.")

    invoice.status = Invoice.Status.SENT
    invoice.save()

    ticket.status = Ticket.Status.INVOICED
    ticket.invoiced_at = timezone.now()
    ticket.save()

    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body="Invoice sent.",
        type=TicketMessage.MessageType.SYSTEM,
    )

    notify(
        ticket.customer,
        "Invoice sent",
        f"An invoice for ticket #{ticket.id} is ready.",
        {"ticket_id": ticket.id, "invoice_id": invoice.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )
