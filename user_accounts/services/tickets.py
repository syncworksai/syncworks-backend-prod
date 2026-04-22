from __future__ import annotations

from dataclasses import dataclass
from math import radians, cos, sin, asin, sqrt
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

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
    ServiceCategory,
)
from user_accounts.models.billing import Invoice

from user_accounts.services.notifications import notify


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
    default = 25
    r = getattr(business, "service_radius_miles", None)
    try:
        r = int(r) if r is not None else default
    except Exception:
        r = default
    if r < 1:
        return 1
    if r > 200:
        return 200
    return r


def _category_ancestor_ids(category: ServiceCategory | None) -> set[int]:
    ids: set[int] = set()
    cur = category
    guard = 0

    while cur is not None and guard < 50:
        try:
            if cur.id:
                ids.add(int(cur.id))
        except Exception:
            pass
        cur = getattr(cur, "parent", None)
        guard += 1

    return ids


def _category_descendant_leaf_ids(category: ServiceCategory | None) -> set[int]:
    if category is None:
        return set()

    try:
        children = list(category.children.all())
    except Exception:
        children = []

    if not children:
        try:
            return {int(category.id)} if category.id else set()
        except Exception:
            return set()

    found: set[int] = set()
    stack = children[:]
    guard = 0

    while stack and guard < 5000:
        cur = stack.pop()
        guard += 1

        try:
            cur_children = list(cur.children.all())
        except Exception:
            cur_children = []

        if not cur_children:
            try:
                if cur.id:
                    found.add(int(cur.id))
            except Exception:
                pass
        else:
            stack.extend(cur_children)

    return found


def _business_service_scope_ids(business: Business) -> set[int]:
    scope: set[int] = set()

    try:
        offered = list(business.services_offered.all())
    except Exception:
        offered = []

    for cat in offered:
        scope.update(_category_descendant_leaf_ids(cat))

    return scope


def _business_can_take_category(business: Business, ticket: Ticket) -> bool:
    if not ticket.category_id:
        return False

    try:
        scoped_leaf_ids = _business_service_scope_ids(business)
        if int(ticket.category_id) in scoped_leaf_ids:
            return True
    except Exception:
        pass

    try:
        ticket_cat = ticket.category
    except Exception:
        ticket_cat = None

    if not ticket_cat:
        return False

    try:
        offered_ids = set(int(x) for x in business.services_offered.values_list("id", flat=True))
    except Exception:
        offered_ids = set()

    if not offered_ids:
        return False

    ticket_ancestors = _category_ancestor_ids(ticket_cat)
    return bool(ticket_ancestors & offered_ids)


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
    qs = Ticket.objects.filter(
        is_marketplace=True,
        assigned_business__isnull=True,
        status=Ticket.Status.NEW,
    ).select_related("category", "service_request").order_by("-created_at")

    if not business or not getattr(business, "is_active", False):
        return qs.none()

    if not getattr(business, "accepts_marketplace_tickets", False):
        return qs.none()

    try:
        if not business.services_offered.exists():
            return qs.none()
    except Exception:
        return qs.none()

    declined_ids = TicketViewEvent.objects.filter(
        business_id=business.id,
        event_type__in=[
            TicketViewEvent.EventType.DECLINED_MARKETPLACE,
            TicketViewEvent.EventType.BUSINESS_DECLINED,
        ],
    ).values_list("ticket_id", flat=True)
    qs = qs.exclude(id__in=declined_ids)

    qs = qs.filter(
        Q(service_zip__isnull=False) & ~Q(service_zip="")
        | Q(service_request__zip_code__isnull=False) & ~Q(service_request__zip_code="")
    )

    base_zip = (getattr(business, "base_zip", "") or "").strip()
    if not base_zip:
        return qs.none()

    exact_zip = qs.filter(Q(service_zip__iexact=base_zip) | Q(service_request__zip_code__iexact=base_zip))
    exact_zip = [t for t in exact_zip if is_ticket_eligible_for_business(t, business)]

    candidates = qs.exclude(Q(service_zip__iexact=base_zip) | Q(service_request__zip_code__iexact=base_zip))

    matched_ids: list[int] = []
    for t in candidates.only(
        "id",
        "service_zip",
        "category_id",
        "is_marketplace",
        "status",
        "assigned_business_id",
        "service_request__zip_code",
        "category__id",
        "category__parent_id",
    ):
        if is_ticket_eligible_for_business(t, business):
            matched_ids.append(t.id)

    combined_ids = [t.id for t in exact_zip] + matched_ids
    if not combined_ids:
        return qs.none()

    return Ticket.objects.filter(id__in=combined_ids).select_related("category", "service_request").distinct().order_by("-created_at")


def ticket_eligible_businesses(ticket: Ticket):
    qs = Business.objects.filter(is_active=True).prefetch_related("services_offered").order_by("name")

    if ticket.is_marketplace:
        qs = qs.filter(accepts_marketplace_tickets=True)

    tzip = _ticket_zip(ticket)
    if not tzip:
        return Business.objects.none()

    matched_ids: list[int] = []

    for b in qs.only("id", "name", "base_zip", "service_radius_miles", "accepts_marketplace_tickets", "is_active"):
        if is_ticket_eligible_for_business(ticket, b):
            matched_ids.append(b.id)

    if not matched_ids:
        return Business.objects.none()

    return Business.objects.filter(id__in=matched_ids).distinct().order_by("name")


def _coerce_radius(service_radius_miles: Optional[int]) -> int:
    default = 25
    if service_radius_miles is None:
        return default
    try:
        r = int(service_radius_miles)
    except Exception:
        return default
    if r < 1:
        return 1
    if r > 200:
        return 200
    return r


def _member_role(member: BusinessMember | None) -> str:
    return str(getattr(member, "role", "") or "").upper()


def _member_can_manage_schedule(member: BusinessMember | None) -> bool:
    if not member:
        return False
    return bool(
        getattr(member, "can_manage_schedule", False)
        or _member_role(member) in {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}
    )


def _member_is_assigned_tech(member: BusinessMember | None, ticket: Ticket) -> bool:
    if not member or not ticket:
        return False
    return int(getattr(ticket, "assigned_member_id", 0) or 0) == int(getattr(member, "user_id", 0) or 0)


def _member_can_complete(member: BusinessMember | None, ticket: Ticket) -> bool:
    if not member:
        return False
    return bool(_member_is_assigned_tech(member, ticket) or getattr(member, "can_close_tickets", False))


def _transition_system_message(ticket: Ticket, actor_user, body: str) -> None:
    TicketMessage.objects.create(
        ticket=ticket,
        sender=actor_user,
        body=body,
        type=TicketMessage.MessageType.SYSTEM,
    )


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

    Ticket.objects.create(
        service_request=sr,
        customer=customer,
        category=category,
        status=Ticket.Status.NEW,
        is_marketplace=bool(is_marketplace),
        service_zip=clean_zip,
        service_address=clean_addr,
        service_radius_miles=clean_radius,
    )

    t = sr.ticket

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
    ticket.scheduled_at = None
    ticket.en_route_at = None
    ticket.on_site_at = None
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
    ticket.scheduled_at = None
    ticket.en_route_at = None
    ticket.on_site_at = None
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


@transaction.atomic
def provider_decline(ticket: Ticket, *, actor_user, business: Business, reason: str = ""):
    if not business or not getattr(business, "is_active", False):
        raise ValueError("Invalid business.")

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

    if ticket.assigned_business_id != business.id:
        raise ValueError("Ticket is not assigned to your business.")

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

    send_ticket_to_marketplace(ticket)


@transaction.atomic
def provider_accept(ticket: Ticket, actor_user):
    if ticket.status not in (Ticket.Status.NEW, Ticket.Status.ASSIGNED):
        raise ValueError("Ticket cannot be accepted in current status.")

    ticket.status = Ticket.Status.ACCEPTED
    ticket.accepted_at = timezone.now()
    ticket.save(update_fields=["status", "accepted_at"])

    notify(
        ticket.customer,
        "Provider accepted",
        f"Your ticket #{ticket.id} was accepted.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Provider accepted the ticket.")


@transaction.atomic
def provider_schedule(ticket: Ticket, actor_user, member: BusinessMember | None):
    if ticket.status not in (Ticket.Status.ACCEPTED, Ticket.Status.ASSIGNED, Ticket.Status.NEW):
        raise ValueError("Ticket cannot be scheduled in current status.")
    if not _member_can_manage_schedule(member):
        raise PermissionDenied("You do not have permission to schedule this ticket.")

    ticket.status = Ticket.Status.SCHEDULED
    ticket.scheduled_at = timezone.now()
    ticket.save(update_fields=["status", "scheduled_at"])

    notify(
        ticket.customer,
        "Job scheduled",
        f"Ticket #{ticket.id} is now scheduled.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Job scheduled.")


@transaction.atomic
def provider_mark_en_route(ticket: Ticket, actor_user, member: BusinessMember | None):
    if ticket.status not in (Ticket.Status.SCHEDULED, Ticket.Status.ACCEPTED):
        raise ValueError("Ticket must be scheduled or accepted before marking En Route.")
    if not _member_is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can mark En Route.")

    ticket.status = Ticket.Status.EN_ROUTE
    ticket.en_route_at = timezone.now()
    ticket.save(update_fields=["status", "en_route_at"])

    notify(
        ticket.customer,
        "Technician en route",
        f"Ticket #{ticket.id} technician is on the way.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Technician marked En Route.")


@transaction.atomic
def provider_mark_on_site(ticket: Ticket, actor_user, member: BusinessMember | None):
    if ticket.status not in (Ticket.Status.EN_ROUTE, Ticket.Status.SCHEDULED, Ticket.Status.ACCEPTED):
        raise ValueError("Ticket must be active before marking On Site.")
    if not _member_is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can mark On Site.")

    ticket.status = Ticket.Status.ON_SITE
    ticket.on_site_at = timezone.now()
    ticket.save(update_fields=["status", "on_site_at"])

    notify(
        ticket.customer,
        "Technician on site",
        f"Ticket #{ticket.id} technician has arrived.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Technician marked On Site.")


@transaction.atomic
def provider_set_needs_quote(ticket: Ticket, actor_user):
    if ticket.status in (Ticket.Status.CANCELLED, Ticket.Status.CLOSED, Ticket.Status.PAID):
        raise ValueError("Ticket cannot request a quote in this status.")

    ticket.status = Ticket.Status.NEEDS_QUOTE
    ticket.save(update_fields=["status"])

    _transition_system_message(ticket, actor_user, "Provider requested an estimate (Needs Quote).")

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
    ticket.save(update_fields=["status"])

    _transition_system_message(ticket, actor_user, f"Estimate sent (${quote.amount}).")

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
    ticket.awaiting_approval_at = None
    ticket.save(update_fields=["status", "awaiting_approval_at"])

    _transition_system_message(ticket, actor_user, "Customer approved the estimate.")

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
    ticket.awaiting_approval_at = timezone.now()
    ticket.save(update_fields=["status", "awaiting_approval_at"])

    msg = "Customer rejected the estimate."
    if (reason or "").strip():
        msg += f" Reason: {reason.strip()}"

    _transition_system_message(ticket, actor_user, msg)

    notify(
        ticket.customer,
        "Estimate rejected",
        f"You rejected the estimate for ticket #{ticket.id}.",
        {"ticket_id": ticket.id, "quote_id": quote.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )


@transaction.atomic
def provider_start(ticket: Ticket, actor_user, member: BusinessMember | None = None):
    if ticket.status not in (
        Ticket.Status.ACCEPTED,
        Ticket.Status.SCHEDULED,
        Ticket.Status.EN_ROUTE,
        Ticket.Status.ON_SITE,
        Ticket.Status.APPROVED,
    ):
        raise ValueError("Ticket must be active before starting.")
    if member is not None and not _member_is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can start work.")

    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.started_at = timezone.now()
    ticket.save(update_fields=["status", "started_at"])

    notify(
        ticket.customer,
        "Work started",
        f"Ticket #{ticket.id} is now in progress.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Work started.")


@transaction.atomic
def provider_complete(ticket: Ticket, actor_user, member: BusinessMember | None = None):
    if ticket.status not in (
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.APPROVED,
        Ticket.Status.ACCEPTED,
        Ticket.Status.ON_SITE,
        Ticket.Status.EN_ROUTE,
        Ticket.Status.SCHEDULED,
    ):
        raise ValueError("Ticket must be in an active work state before completing.")
    if member is not None and not _member_can_complete(member, ticket):
        raise PermissionDenied("You do not have permission to complete this ticket.")

    ticket.status = Ticket.Status.COMPLETED
    ticket.completed_at = timezone.now()
    ticket.save(update_fields=["status", "completed_at"])

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

    _transition_system_message(ticket, actor_user, "Work completed.")


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
    ticket.save(update_fields=["status", "cancelled_at"])

    notify(
        ticket.customer,
        "Ticket cancelled",
        f"Ticket #{ticket.id} cancelled.",
        {"ticket_id": ticket.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )

    _transition_system_message(ticket, actor_user, "Ticket cancelled.")


@transaction.atomic
def provider_send_invoice(ticket: Ticket, invoice: Invoice, actor_user):
    belongs = False

    try:
        if getattr(invoice, "ticket_id", None) is not None:
            belongs = int(invoice.ticket_id) == int(ticket.id)
    except Exception:
        pass

    if not belongs:
        raise ValueError("Invoice does not belong to this ticket.")

    if not invoice.ticket_id:
        invoice.ticket = ticket

    try:
        invoice.recompute_totals_from_lines(save=True)
    except Exception:
        pass

    invoice.status = Invoice.Status.SENT
    invoice.save()

    ticket.status = Ticket.Status.INVOICED
    ticket.invoiced_at = timezone.now()
    ticket.total_amount_cents = int((invoice.total or 0) * 100)
    ticket.payment_method = invoice.payment_method or Ticket.PaymentMethod.CARD
    ticket.save(update_fields=["status", "invoiced_at", "total_amount_cents", "payment_method"])

    _transition_system_message(ticket, actor_user, "Invoice ready for payment.")

    notify(
        ticket.customer,
        "Invoice ready for payment",
        f"An invoice for ticket #{ticket.id} is ready.",
        {"ticket_id": ticket.id, "invoice_id": invoice.id},
        type=Notification.TYPE_TICKET,
        actor=actor_user,
    )