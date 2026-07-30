from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone

from platform_affiliates.models import AffiliateCommissionLedger, AffiliatePartner
from user_accounts.models import (
    AuditLog,
    Business,
    BusinessMember,
    StripeConnectProfile,
    Ticket,
)
from user_accounts.services.god_mode import is_god_mode


CLOSED_TICKET_STATUSES = {
    Ticket.Status.COMPLETED,
    Ticket.Status.PAID,
    Ticket.Status.CANCELLED,
    Ticket.Status.CLOSED,
}


def _section(
    *,
    section_id: str,
    title: str,
    summary: str,
    priority: str = "normal",
    count: int | None = None,
    change: int | None = None,
    details_url: str = "",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "summary": summary,
        "priority": priority,
        "count": count,
        "change_since_last_brief": change,
        "details_url": details_url,
        "actions": (
            [{"label": "View details", "url": details_url}]
            if details_url
            else []
        ),
        "items": items or [],
    }


def _last_briefing_at(user):
    previous = (
        AuditLog.objects.filter(
            actor=user,
            action="sync_ai.briefing.completed",
        )
        .order_by("-created_at")
        .first()
    )
    return previous.created_at if previous else timezone.now() - timedelta(hours=24)


def _owned_or_member_businesses(user):
    member_ids = BusinessMember.objects.filter(
        user=user,
        is_active=True,
    ).values_list("business_id", flat=True)
    return Business.objects.filter(
        Q(owner=user) | Q(id__in=member_ids),
        is_active=True,
    ).distinct()


def _personal_collector(user, since):
    active = Ticket.objects.filter(customer=user, archived_at__isnull=True).exclude(
        status__in=CLOSED_TICKET_STATUSES
    )
    new_count = Ticket.objects.filter(customer=user, created_at__gt=since).count()
    needs_attention = active.filter(
        status__in=[
            Ticket.Status.NEW,
            Ticket.Status.NEEDS_QUOTE,
            Ticket.Status.AWAITING_APPROVAL,
            Ticket.Status.QUOTE_REJECTED,
        ]
    ).count()
    return _section(
        section_id="personal_requests",
        title="Personal requests",
        summary=(
            f"You have {active.count()} active requests. "
            f"{needs_attention} currently need attention."
        ),
        priority="high" if needs_attention else "normal",
        count=active.count(),
        change=new_count,
        details_url="/customer/requests",
    )


def _calendar_collector(user, since):
    model = apps.get_model("personal_calendar", "PersonalCalendarEvent")
    now = timezone.now()
    end = now + timedelta(days=7)
    upcoming = model.objects.filter(
        owner=user,
        status="ACTIVE",
        start_at__gte=now,
        start_at__lte=end,
    ).order_by("start_at")
    items = [
        {
            "id": event.id,
            "title": event.title,
            "start_at": event.start_at.isoformat(),
            "location": event.location_name or event.address_line1,
            "url": "/customer/calendar",
        }
        for event in upcoming[:5]
    ]
    return _section(
        section_id="calendar",
        title="Calendar",
        summary=f"You have {upcoming.count()} events scheduled in the next seven days.",
        count=upcoming.count(),
        change=model.objects.filter(owner=user, created_at__gt=since).count(),
        details_url="/customer/calendar",
        items=items,
    )


def _business_collector(user, since):
    sections = []
    for business in _owned_or_member_businesses(user):
        tickets = Ticket.objects.filter(
            Q(assigned_business=business) | Q(payer_business=business),
            archived_at__isnull=True,
        ).distinct()
        active = tickets.exclude(status__in=CLOSED_TICKET_STATUSES)
        unassigned = active.filter(assigned_member__isnull=True).count()
        new_count = tickets.filter(created_at__gt=since).count()
        needs_attention = active.filter(
            status__in=[
                Ticket.Status.NEW,
                Ticket.Status.NEEDS_QUOTE,
                Ticket.Status.AWAITING_APPROVAL,
                Ticket.Status.QUOTE_REJECTED,
            ]
        ).count()
        stripe = StripeConnectProfile.objects.filter(business=business).first()
        stripe_ready = bool(
            stripe
            and stripe.onboarding_completed
            and stripe.charges_enabled
            and stripe.payouts_enabled
        )
        summary = (
            f"{business.name} has {new_count} new tickets since your last briefing, "
            f"{active.count()} active tickets, and {needs_attention} needing attention. "
            f"Stripe payments are {'ready' if stripe_ready else 'not fully configured'}."
        )
        sections.append(
            _section(
                section_id=f"business_{business.id}",
                title=business.name,
                summary=summary,
                priority="high" if needs_attention or not stripe_ready else "normal",
                count=active.count(),
                change=new_count,
                details_url=f"/tickets?business_id={business.id}",
                items=[
                    {
                        "label": "Unassigned tickets",
                        "value": unassigned,
                        "url": f"/tickets?business_id={business.id}&assignment=unassigned",
                    },
                    {
                        "label": "Stripe ready",
                        "value": stripe_ready,
                        "url": f"/sbo/settings?business_id={business.id}&section=payments",
                    },
                ],
            )
        )
    return sections


def _affiliate_collector(user, since):
    partner = AffiliatePartner.objects.filter(user=user).first()
    if not partner:
        return None
    ledger = AffiliateCommissionLedger.objects.filter(affiliate=partner)
    pending = ledger.exclude(status="PAID").aggregate(total=Sum("commission_amount"))["total"] or Decimal("0")
    recent = ledger.filter(created_at__gt=since).aggregate(total=Sum("commission_amount"))["total"] or Decimal("0")
    return _section(
        section_id="affiliate",
        title="Affiliate",
        summary=f"You have ${pending:.2f} in unpaid commissions and ${recent:.2f} added since your last briefing.",
        count=ledger.count(),
        change=ledger.filter(created_at__gt=since).count(),
        details_url="/affiliate",
    )


def _god_mode_collector(user, since):
    if not is_god_mode(user):
        return None
    User = get_user_model()
    new_users = User.objects.filter(date_joined__gt=since).count()
    new_businesses = Business.objects.filter(created_at__gt=since).count()
    active_businesses = Business.objects.filter(is_active=True)
    ready_business_ids = StripeConnectProfile.objects.filter(
        onboarding_completed=True,
        charges_enabled=True,
        payouts_enabled=True,
    ).values_list("business_id", flat=True)
    missing_stripe = active_businesses.exclude(id__in=ready_business_ids).count()
    new_tickets = Ticket.objects.filter(created_at__gt=since).count()
    new_affiliates = AffiliatePartner.objects.filter(created_at__gt=since).count()
    commissions = AffiliateCommissionLedger.objects.filter(created_at__gt=since).aggregate(
        total=Sum("commission_amount")
    )["total"] or Decimal("0")
    summary = (
        f"Since your last briefing, SyncWorks added {new_users} users, {new_businesses} businesses, "
        f"{new_tickets} tickets, and {new_affiliates} affiliates. "
        f"{missing_stripe} active businesses are not fully Stripe-ready. "
        f"Affiliate commissions increased by ${commissions:.2f}."
    )
    return _section(
        section_id="god_mode",
        title="SyncWorks God Mode",
        summary=summary,
        priority="high" if missing_stripe else "normal",
        count=new_users + new_businesses + new_tickets + new_affiliates,
        change=new_users + new_businesses + new_tickets + new_affiliates,
        details_url="/god-mode",
        items=[
            {"label": "New users", "value": new_users, "url": "/god-mode/users"},
            {"label": "New businesses", "value": new_businesses, "url": "/god-mode/businesses"},
            {
                "label": "Businesses missing Stripe",
                "value": missing_stripe,
                "url": "/god-mode/businesses?stripe_status=incomplete",
            },
            {"label": "New tickets", "value": new_tickets, "url": "/god-mode/tickets"},
            {"label": "New affiliates", "value": new_affiliates, "url": "/god-mode/affiliates"},
        ],
    )


def build_role_aware_briefing(user):
    since = _last_briefing_at(user)
    sections: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    collectors: list[tuple[str, Callable[[], Any]]] = [
        ("personal", lambda: _personal_collector(user, since)),
        ("calendar", lambda: _calendar_collector(user, since)),
        ("business", lambda: _business_collector(user, since)),
        ("affiliate", lambda: _affiliate_collector(user, since)),
        ("god_mode", lambda: _god_mode_collector(user, since)),
    ]

    for name, collector in collectors:
        try:
            result = collector()
            if isinstance(result, list):
                sections.extend(result)
            elif result:
                sections.append(result)
        except Exception as exc:
            errors.append({"collector": name, "error": str(exc)[:180]})

    total_updates = sum(int(section.get("change_since_last_brief") or 0) for section in sections)
    high_priority = [section for section in sections if section.get("priority") == "high"]
    payload = {
        "generated_at": timezone.now().isoformat(),
        "since": since.isoformat(),
        "total_updates": total_updates,
        "high_priority_count": len(high_priority),
        "roles": {
            "personal": True,
            "business": bool(_owned_or_member_businesses(user).exists()),
            "affiliate": AffiliatePartner.objects.filter(user=user).exists(),
            "god_mode": is_god_mode(user),
        },
        "sections": sections,
        "errors": errors,
        "partial_success": bool(errors),
    }
    AuditLog.objects.create(
        actor=user,
        action="sync_ai.briefing.completed",
        metadata={
            "total_updates": total_updates,
            "section_ids": [section["id"] for section in sections],
            "error_collectors": [error["collector"] for error in errors],
            "god_mode": is_god_mode(user),
        },
    )
    return payload
