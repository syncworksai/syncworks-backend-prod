from __future__ import annotations

from typing import Any

from user_accounts.models import Business, BusinessMember, Ticket
from user_accounts.models.billing import Invoice


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _request_user(request):
    return getattr(request, "user", None) if request is not None else None


def _active_business(request) -> Business | None:
    if request is None:
        return None

    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or ""
    )
    try:
        business_id = int(str(raw).strip())
    except (TypeError, ValueError):
        return None

    business = Business.objects.filter(id=business_id, is_active=True).first()
    user = _request_user(request)
    if not business or not user:
        return None
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return business
    if business.owner_id == getattr(user, "id", None):
        return business
    if BusinessMember.objects.filter(business_id=business.id, user_id=user.id, is_active=True).exists():
        return business
    return None


def _membership(user, business: Business | None) -> BusinessMember | None:
    if not user or not business:
        return None
    return BusinessMember.objects.filter(
        business_id=business.id,
        user_id=getattr(user, "id", None),
        is_active=True,
    ).first()


def _member_role(member: BusinessMember | None) -> str:
    return _upper(getattr(member, "role", ""))


def _can_manage(member: BusinessMember | None, business: Business | None, user) -> bool:
    if not user or not business:
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    if business.owner_id == getattr(user, "id", None):
        return True
    role = _member_role(member)
    return bool(
        role in {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}
        or getattr(member, "can_assign_tickets", False)
        or getattr(member, "can_manage_schedule", False)
        or getattr(member, "can_close_tickets", False)
    )


def _can_field_work(member: BusinessMember | None, ticket: Ticket, business: Business | None, user) -> bool:
    if _can_manage(member, business, user):
        return True
    return bool(
        member
        and int(getattr(ticket, "assigned_member_id", 0) or 0)
        == int(getattr(member, "user_id", 0) or 0)
    )


def _latest_quote(ticket: Ticket):
    try:
        return ticket.quotes.order_by("-created_at").first()
    except Exception:
        return None


def _latest_invoice(ticket: Ticket):
    try:
        return ticket.invoices.order_by("-created_at").first()
    except Exception:
        return None


def _action(key: str, label: str, *, tone: str = "cyan", tab: str = "", endpoint: str = "") -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "tone": tone,
        "tab": tab,
        "endpoint": endpoint,
    }


def build_ticket_workflow(ticket: Ticket, request=None) -> dict[str, Any]:
    """Return the canonical, actor-aware workflow contract for one ticket.

    This deliberately interprets the current schema instead of introducing new
    database statuses. Frontend screens and future SYNC/AI features should use
    this contract rather than independently guessing the next valid action.
    """

    user = _request_user(request)
    status = _upper(ticket.status) or "NEW"
    active_business = _active_business(request)
    member = _membership(user, active_business)
    latest_quote = _latest_quote(ticket)
    latest_invoice = _latest_invoice(ticket)

    is_platform = bool(
        user
        and (getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))
    )
    is_customer = bool(user and ticket.customer_id == getattr(user, "id", None))
    is_assigned_business = bool(
        active_business and ticket.assigned_business_id == active_business.id
    )
    is_opportunity = bool(
        active_business
        and ticket.is_marketplace
        and ticket.assigned_business_id is None
        and status == "NEW"
    )
    is_business_actor = bool(is_platform or is_assigned_business or is_opportunity)
    can_manage = bool(is_platform or _can_manage(member, active_business, user))
    can_field_work = bool(is_platform or _can_field_work(member, ticket, active_business, user))

    context = "OPPORTUNITY" if is_opportunity else "ACTIVE_JOB" if ticket.assigned_business_id else "REQUEST"
    waiting_on = "SYNCWORKS"
    phase = "OPEN"
    phase_label = "Request open"
    progress_current = 1
    progress_total = 9
    primary = None
    secondary: list[dict[str, str]] = []
    blocked_reasons: dict[str, str] = {}

    terminal = status in {"CANCELLED", "CLOSED"} or bool(ticket.archived_at)
    if terminal:
        phase = "CANCELLED" if status == "CANCELLED" else "CLOSED"
        phase_label = "Cancelled" if status == "CANCELLED" else "Closed"
        waiting_on = "NONE"
        progress_current = progress_total
    elif status == "PAID":
        phase = "PAID"
        phase_label = "Payment received"
        waiting_on = "BUSINESS"
        progress_current = 9
        if is_business_actor and can_manage:
            primary = _action("CLOSE_TICKET", "Close Ticket", tone="emerald")
    elif status == "INVOICED" or _upper(getattr(latest_invoice, "status", "")) in {"SENT", "OPEN"}:
        phase = "PAYMENT"
        phase_label = "Payment due"
        progress_current = 8
        if is_customer:
            waiting_on = "CUSTOMER"
            primary = _action("PAY_INVOICE", "Pay Invoice", tone="emerald", tab="invoice")
        else:
            waiting_on = "CUSTOMER"
            secondary.append(_action("OPEN_INVOICE", "Open Invoice", tone="amber", tab="invoice"))
    elif status in {"COMPLETED", "AWAITING_APPROVAL"}:
        phase = "WORK_COMPLETE"
        phase_label = "Work complete"
        progress_current = 7
        if is_business_actor:
            waiting_on = "BUSINESS"
            primary = _action("SEND_INVOICE", "Send Invoice", tone="emerald", tab="invoice")
        else:
            waiting_on = "BUSINESS"
    elif status == "IN_PROGRESS":
        phase = "IN_PROGRESS"
        phase_label = "Work in progress"
        progress_current = 6
        waiting_on = "BUSINESS"
        if is_business_actor and can_field_work:
            primary = _action("COMPLETE_JOB", "Complete Job", tone="emerald", endpoint="complete")
    elif status == "ON_SITE":
        phase = "ON_SITE"
        phase_label = "Provider is on site"
        progress_current = 6
        waiting_on = "BUSINESS"
        if is_business_actor and can_field_work:
            primary = _action("START_JOB", "Start Job", endpoint="start")
    elif status == "EN_ROUTE":
        phase = "EN_ROUTE"
        phase_label = "Provider is en route"
        progress_current = 5
        waiting_on = "BUSINESS"
        if is_business_actor and can_field_work:
            primary = _action("MARK_ON_SITE", "Mark On Site", tone="fuchsia", endpoint="on-site")
    elif status == "SCHEDULED":
        phase = "SCHEDULED"
        phase_label = "Service scheduled"
        progress_current = 5
        waiting_on = "BUSINESS"
        if is_business_actor:
            if not ticket.assigned_member_id and can_manage:
                primary = _action("ASSIGN_TECHNICIAN", "Assign Technician", tone="sky")
            elif can_field_work:
                primary = _action("MARK_EN_ROUTE", "Start Travel", tone="sky", endpoint="en-route")
    elif status == "APPROVED" or _upper(getattr(latest_quote, "status", "")) == "APPROVED":
        phase = "APPROVED"
        phase_label = "Quote approved"
        progress_current = 4
        waiting_on = "BUSINESS"
        if is_business_actor and can_manage:
            primary = _action("SCHEDULE_SERVICE", "Schedule Service", tone="amber", endpoint="schedule")
    elif status in {"QUOTED", "QUOTE_REJECTED"} or _upper(getattr(latest_quote, "status", "")) in {"SENT", "REJECTED"}:
        rejected = status == "QUOTE_REJECTED" or _upper(getattr(latest_quote, "status", "")) == "REJECTED"
        phase = "QUOTE_REVISION" if rejected else "CUSTOMER_DECISION"
        phase_label = "Quote revision needed" if rejected else "Quote ready"
        progress_current = 3
        if rejected:
            waiting_on = "BUSINESS"
            if is_business_actor:
                primary = _action("SEND_QUOTE", "Revise Quote", tone="amber", tab="quote")
        else:
            waiting_on = "CUSTOMER"
            if is_customer:
                primary = _action("REVIEW_QUOTE", "Review Quote", tone="amber", tab="quote")
            else:
                secondary.append(_action("OPEN_QUOTE", "Open Quote", tone="amber", tab="quote"))
    elif status == "NEEDS_QUOTE":
        phase = "QUOTE_NEEDED"
        phase_label = "Quote needed"
        progress_current = 3
        waiting_on = "BUSINESS"
        if is_business_actor:
            primary = _action("SEND_QUOTE", "Create Quote", tone="amber", tab="quote")
    elif status in {"ACCEPTED"}:
        phase = "ACCEPTED"
        phase_label = "Request accepted"
        progress_current = 2
        waiting_on = "BUSINESS"
        if is_business_actor and can_manage:
            primary = _action("SCHEDULE_SERVICE", "Schedule Service", tone="amber", endpoint="schedule")
            secondary.append(_action("CREATE_QUOTE", "Create Quote", tone="slate", tab="quote"))
    elif status in {"NEW", "ASSIGNED"}:
        progress_current = 1
        if is_opportunity:
            phase = "OPPORTUNITY"
            phase_label = "Marketplace opportunity"
            waiting_on = "BUSINESS"
            primary = _action("ACCEPT_REQUEST", "Accept Request", endpoint="accept")
            secondary.append(_action("DECLINE_REQUEST", "Decline", tone="rose", endpoint="decline_marketplace"))
        elif ticket.assigned_business_id:
            phase = "RESPONSE_NEEDED"
            phase_label = "Business response needed"
            waiting_on = "BUSINESS"
            if is_business_actor:
                primary = _action("ACCEPT_REQUEST", "Accept Request", endpoint="accept")
        else:
            phase = "MATCHING"
            phase_label = "Finding a provider"
            waiting_on = "BUSINESS"

    if not terminal:
        secondary.append(_action("MESSAGE", "Message", tone="slate", tab="messages"))

    if primary is None:
        if waiting_on == "CUSTOMER" and is_customer:
            blocked_reasons["primary"] = "Your next step will appear when the required record is available."
        elif waiting_on == "BUSINESS" and is_business_actor and not (can_manage or can_field_work):
            blocked_reasons["primary"] = "Your company role or assignment does not allow the next operation."

    return {
        "version": 1,
        "context": context,
        "phase": phase,
        "phase_label": phase_label,
        "status": status,
        "status_label": ticket.get_status_display(),
        "waiting_on": waiting_on,
        "waiting_on_label": {
            "CUSTOMER": "Waiting on you" if is_customer else "Waiting on customer",
            "BUSINESS": "Waiting on business" if is_customer else "Waiting on your team",
            "SYNCWORKS": "SyncWorks is processing",
            "NONE": "No action needed",
        }.get(waiting_on, waiting_on.title()),
        "primary_action": primary,
        "secondary_actions": secondary,
        "allowed_action_keys": [
            action["key"] for action in ([primary] if primary else []) + secondary
        ],
        "progress": {
            "current": progress_current,
            "total": progress_total,
            "percent": round((progress_current / progress_total) * 100),
        },
        "permissions": {
            "is_customer": is_customer,
            "is_business_actor": is_business_actor,
            "can_manage": can_manage,
            "can_field_work": can_field_work,
        },
        "blocked_reasons": blocked_reasons,
    }