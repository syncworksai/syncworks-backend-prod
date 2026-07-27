from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from customer_health.models import CustomerHealthProfile
from user_accounts.models import (
    BusinessPartnerInvitation,
    FinancePlan,
    FinanceSnapshot,
    Prospect,
    ServiceRequest,
    Ticket,
    TicketMessage,
)


ACTIVE_TICKET_STATUSES = [
    "NEW",
    "ASSIGNED",
    "ACCEPTED",
    "SCHEDULED",
    "EN_ROUTE",
    "ON_SITE",
    "IN_PROGRESS",
    "NEEDS_QUOTE",
    "QUOTED",
    "APPROVED",
    "AWAITING_APPROVAL",
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


def personal_snapshot(user) -> dict[str, Any]:
    now = timezone.now()

    requests = ServiceRequest.objects.filter(customer=user)
    active_requests = requests.exclude(status__in=["CANCELLED", "CLOSED"])

    customer_tickets = Ticket.objects.filter(customer=user)
    active_tickets = customer_tickets.filter(status__in=ACTIVE_TICKET_STATUSES)

    recent_messages = TicketMessage.objects.filter(
        ticket__customer=user,
        created_at__gte=now - timedelta(days=14),
    )

    health = CustomerHealthProfile.objects.filter(user=user).first()
    finance_snapshot = FinanceSnapshot.objects.filter(user=user).first()
    finance_plans = FinancePlan.objects.filter(user=user)
    active_finance_plans = finance_plans.filter(status="ACTIVE")

    health_summary = {
        "profile_available": bool(health),
        "updated_at": health.updated_at.isoformat() if health else None,
        "saved_workout_count": len(health.workouts_json or []) if health else 0,
        "history_entry_count": len(health.history_json or []) if health else 0,
        "progress_entry_count": len(health.progress_json or []) if health else 0,
        "snapshot_available": bool((health.snapshot_json or {}) if health else False),
    }

    finance_payload = finance_snapshot.payload if finance_snapshot else {}
    finance_summary = {
        "snapshot_available": bool(finance_snapshot),
        "snapshot_updated_at": (
            finance_snapshot.created_at.isoformat()
            if finance_snapshot and finance_snapshot.created_at
            else None
        ),
        "active_plan_count": _safe_count(active_finance_plans),
        "plan_count": _safe_count(finance_plans),
        "cash_on_hand_recorded": "cash_on_hand" in finance_payload,
        "monthly_income_recorded": "monthly_income" in finance_payload,
        "debt_count": len(finance_payload.get("debts") or []),
        "fixed_obligation_count": len(finance_payload.get("fixed_obligations") or []),
    }

    return {
        "service_requests": {
            "total": _safe_count(requests),
            "active": _safe_count(active_requests),
            "recent_titles": _latest_titles(
                active_requests.order_by("-created_at"),
                "title",
            ),
        },
        "tickets": {
            "total": _safe_count(customer_tickets),
            "active": _safe_count(active_tickets),
            "awaiting_approval": _safe_count(
                customer_tickets.filter(status="AWAITING_APPROVAL")
            ),
            "scheduled": _safe_count(customer_tickets.filter(status="SCHEDULED")),
        },
        "inbox": {
            "recent_ticket_messages_14d": _safe_count(recent_messages),
        },
        "health": health_summary,
        "finance": finance_summary,
    }


def business_snapshot(user, business) -> dict[str, Any]:
    now = timezone.now()

    tickets = Ticket.objects.filter(
        Q(assigned_business=business) | Q(payer_business=business)
    ).distinct()
    active = tickets.filter(status__in=ACTIVE_TICKET_STATUSES)
    blocked = active.filter(status__in=["BLOCKED", "WAITING", "ON_HOLD"])
    overdue = active.filter(
        scheduled_at__isnull=False,
        scheduled_at__lt=now,
    ).exclude(status__in=["COMPLETED", "CLOSED", "CANCELLED", "PAID"])
    unassigned = active.filter(assigned_member__isnull=True)

    leads = Prospect.objects.filter(pipeline__business=business)
    open_leads = leads.exclude(stage__name__in=CLOSED_LEAD_STAGES)
    follow_up_due = open_leads.filter(
        next_follow_up_at__isnull=False,
        next_follow_up_at__lte=now,
    )

    invitations = BusinessPartnerInvitation.objects.filter(
        Q(inviting_business=business) | Q(target_business=business)
    )
    pending_invitations = invitations.filter(status="PENDING")

    recent_messages = TicketMessage.objects.filter(
        ticket__assigned_business=business,
        created_at__gte=now - timedelta(days=14),
    )

    gross_open_cents = 0
    try:
        gross_open_cents = sum(
            int(value or 0)
            for value in active.values_list("total_amount_cents", flat=True)
        )
    except Exception:
        gross_open_cents = 0

    return {
        "operations": {
            "active_jobs": _safe_count(active),
            "blocked_or_waiting": _safe_count(blocked),
            "overdue_scheduled": _safe_count(overdue),
            "unassigned": _safe_count(unassigned),
            "in_progress": _safe_count(
                active.filter(status__in=["EN_ROUTE", "ON_SITE", "IN_PROGRESS"])
            ),
            "awaiting_approval": _safe_count(
                tickets.filter(status="AWAITING_APPROVAL")
            ),
            "open_job_value_cents": gross_open_cents,
            "recent_job_titles": _latest_titles(
                active.order_by("-created_at"),
                "work_title",
            ),
        },
        "leads": {
            "open": _safe_count(open_leads),
            "follow_up_due": _safe_count(follow_up_due),
            "total": _safe_count(leads),
        },
        "partners": {
            "pending_invitations": _safe_count(pending_invitations),
        },
        "inbox": {
            "recent_ticket_messages_14d": _safe_count(recent_messages),
        },
        "business_profile": {
            "accepts_marketplace_tickets": bool(
                business.accepts_marketplace_tickets
            ),
            "service_radius_miles": business.effective_service_radius_miles(),
            "service_count": _safe_count(business.services_offered.all()),
        },
    }
