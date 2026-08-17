from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from user_accounts.models import (
    BusinessPartnerInvitation,
    Prospect,
    ServiceRequest,
    Ticket,
    TicketMessage,
)
from user_accounts.services.finance_intelligence import build_finance_briefing

from .health_context import build_sync_health_context


ACTIVE_TICKET_STATUSES = [
    "NEW", "ASSIGNED", "ACCEPTED", "SCHEDULED", "EN_ROUTE", "ON_SITE",
    "IN_PROGRESS", "NEEDS_QUOTE", "QUOTED", "APPROVED", "AWAITING_APPROVAL",
]
CLOSED_LEAD_STAGES = ["WON", "LOST", "CLOSED", "ARCHIVED", "CONVERTED"]


def _safe_count(queryset) -> int:
    try:
        return queryset.count()
    except Exception:
        return 0


def _latest_titles(queryset, field: str, limit: int = 5) -> list[str]:
    try:
        values = queryset.values_list(field, flat=True)[:limit]
        return [str(value)[:120] for value in values if value]
    except Exception:
        return []


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _finance_summary(user) -> dict[str, Any]:
    """Expose the same Finance decision engine to SYNC without leaking raw transactions."""
    try:
        briefing = build_finance_briefing(user)
    except Exception:
        return {"available": False}

    summary = briefing.get("summary") or {}
    debt = briefing.get("debt_strategy") or {}
    avalanche = debt.get("avalanche") or []
    top_target = avalanche[0] if avalanche else None
    return {
        "available": True,
        "as_of": str(briefing.get("as_of") or ""),
        "safe_to_spend_now": _money(summary.get("safe_to_spend_now")),
        "available_cash": _money(summary.get("available_cash")),
        "known_30_day_obligations": _money(summary.get("known_30_day_obligations")),
        "month_cash_flow": _money(summary.get("month_cash_flow")),
        "total_debt": _money(summary.get("total_debt")),
        "credit_utilization_percent": summary.get("credit_utilization_percent"),
        "budget_headroom_remaining": _money(summary.get("budget_headroom_remaining")),
        "active_budget_count": (briefing.get("counts") or {}).get("active_budgets", 0),
        "alerts": [
            {"severity": item.get("severity"), "code": item.get("code"), "message": item.get("message")}
            for item in (briefing.get("alerts") or [])[:5]
        ],
        "recommended_actions": [
            {"priority": item.get("priority"), "code": item.get("code"), "title": item.get("title"), "detail": item.get("detail")}
            for item in (briefing.get("actions") or [])[:5]
        ],
        "debt_strategy": {
            "recommended_method": debt.get("recommended_method"),
            "top_target": ({
                "name": top_target.get("name"),
                "balance": _money(top_target.get("balance")),
                "apr": _money(top_target.get("apr")) if top_target.get("apr") is not None else None,
                "minimum_payment": _money(top_target.get("minimum_payment")),
            } if top_target else None),
        },
    }


def personal_snapshot(user) -> dict[str, Any]:
    now = timezone.now()
    requests = ServiceRequest.objects.filter(customer=user)
    active_requests = requests.exclude(status__in=["CANCELLED", "CLOSED"])
    customer_tickets = Ticket.objects.filter(customer=user)
    active_tickets = customer_tickets.filter(status__in=ACTIVE_TICKET_STATUSES)
    recent_messages = TicketMessage.objects.filter(ticket__customer=user, created_at__gte=now - timedelta(days=14))

    return {
        "service_requests": {
            "total": _safe_count(requests),
            "active": _safe_count(active_requests),
            "recent_titles": _latest_titles(active_requests.order_by("-created_at"), "title"),
        },
        "tickets": {
            "total": _safe_count(customer_tickets),
            "active": _safe_count(active_tickets),
            "awaiting_approval": _safe_count(customer_tickets.filter(status="AWAITING_APPROVAL")),
            "scheduled": _safe_count(customer_tickets.filter(status="SCHEDULED")),
        },
        "inbox": {"recent_ticket_messages_14d": _safe_count(recent_messages)},
        "health": build_sync_health_context(user),
        "finance": _finance_summary(user),
    }


def business_snapshot(user, business) -> dict[str, Any]:
    now = timezone.now()
    tickets = Ticket.objects.filter(Q(assigned_business=business) | Q(payer_business=business)).distinct()
    active = tickets.filter(status__in=ACTIVE_TICKET_STATUSES)
    blocked = active.filter(status__in=["BLOCKED", "WAITING", "ON_HOLD"])
    overdue = active.filter(scheduled_at__isnull=False, scheduled_at__lt=now).exclude(status__in=["COMPLETED", "CLOSED", "CANCELLED", "PAID"])
    unassigned = active.filter(assigned_member__isnull=True)
    leads = Prospect.objects.filter(pipeline__business=business)
    open_leads = leads.exclude(stage__name__in=CLOSED_LEAD_STAGES)
    follow_up_due = open_leads.filter(next_follow_up_at__isnull=False, next_follow_up_at__lte=now)
    invitations = BusinessPartnerInvitation.objects.filter(Q(inviting_business=business) | Q(target_business=business))
    recent_messages = TicketMessage.objects.filter(ticket__assigned_business=business, created_at__gte=now - timedelta(days=14))

    try:
        gross_open_cents = sum(int(value or 0) for value in active.values_list("total_amount_cents", flat=True))
    except Exception:
        gross_open_cents = 0

    return {
        "operations": {
            "active_jobs": _safe_count(active),
            "blocked_or_waiting": _safe_count(blocked),
            "overdue_scheduled": _safe_count(overdue),
            "unassigned": _safe_count(unassigned),
            "in_progress": _safe_count(active.filter(status__in=["EN_ROUTE", "ON_SITE", "IN_PROGRESS"])),
            "awaiting_approval": _safe_count(tickets.filter(status="AWAITING_APPROVAL")),
            "open_job_value_cents": gross_open_cents,
            "recent_job_titles": _latest_titles(active.order_by("-created_at"), "work_title"),
        },
        "leads": {"open": _safe_count(open_leads), "follow_up_due": _safe_count(follow_up_due), "total": _safe_count(leads)},
        "partners": {"pending_invitations": _safe_count(invitations.filter(status="PENDING"))},
        "inbox": {"recent_ticket_messages_14d": _safe_count(recent_messages)},
        "business_profile": {
            "accepts_marketplace_tickets": bool(business.accepts_marketplace_tickets),
            "service_radius_miles": business.effective_service_radius_miles(),
            "service_count": _safe_count(business.services_offered.all()),
        },
    }
