"""Read-only, idempotent task discovery for the private Sync Assist pilot.

No external communications or execution. This scanner is callable from a Django
management command; it is not a scheduler and must not be described as live 24/7
until a verified worker/cron invokes it independently of browser sessions.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from user_accounts.models import AuditLog, Business, Invoice, PMRentCharge, PMWorkOrder, ServiceRequest, Ticket
from .assist_pilot_views import CREATED, PILOT_EMAIL

SCAN = "sync_assist.pilot.discovery_scan"
MAX_NEW_PER_RUN = 10
MAX_TOTAL_AUTO = 200
LOOKBACK_DAYS = 30


def _candidates(user):
    cutoff = timezone.now() - timedelta(days=LOOKBACK_DAYS)
    business_ids = list(Business.objects.filter(owner=user, is_active=True, is_demo=False).values_list("id", flat=True))
    if not business_ids:
        return [], {"businesses": 0, "service_requests": 0, "tickets": 0, "invoices": 0, "pm_work_orders": 0, "pm_rent_charges": 0}

    # Scope by explicit business ownership, never by arbitrary customer identity.
    rows = []
    counts = {"businesses": len(business_ids), "service_requests": 0, "tickets": 0, "invoices": 0, "pm_work_orders": 0, "pm_rent_charges": 0}
    requests = ServiceRequest.objects.filter(
        target_business_id__in=business_ids,
        status__in=[ServiceRequest.Status.NEW, ServiceRequest.Status.SENT],
        created_at__gte=cutoff,
    ).order_by("created_at", "id")[:30]
    for req in requests:
        counts["service_requests"] += 1
        rows.append({
            "source_key": f"service-request:{req.pk}",
            "kind": "LEAD_FOLLOW_UP",
            "title": f"Review new service request #{req.pk}"[:140],
            "description": f"Request: {req.title[:140]}. Review and prepare a customer response; do not send automatically.",
        })

    tickets = Ticket.objects.filter(
        assigned_business_id__in=business_ids,
        status__in=[Ticket.Status.NEW, Ticket.Status.AWAITING_APPROVAL],
        created_at__gte=cutoff,
    ).order_by("created_at", "id")[:30]
    for ticket in tickets:
        counts["tickets"] += 1
        rows.append({
            "source_key": f"ticket:{ticket.pk}:{ticket.status}",
            "kind": "TICKET_REVIEW",
            "title": f"Review ticket #{ticket.pk} ({ticket.status})",
            "description": f"Job: {(ticket.work_title or 'Service ticket')[:140]}. Check next steps and prepare for approval.",
        })

    invoices = Invoice.objects.filter(
        ticket__assigned_business_id__in=business_ids,
        status=Invoice.Status.SENT,
        due_date__lt=timezone.localdate(),
        due_date__isnull=False,
    ).order_by("due_date", "id")[:30]
    for invoice in invoices:
        counts["invoices"] += 1
        rows.append({
            "source_key": f"overdue-invoice:{invoice.pk}",
            "kind": "INVOICE_REMINDER",
            "title": f"Review overdue invoice #{invoice.pk}",
            "description": f"Due date: {invoice.due_date.isoformat()}. Prepare a reminder for owner approval; do not contact customer.",
        })
    pm_orders = PMWorkOrder.objects.filter(
        business_id__in=business_ids,
        status__in=[PMWorkOrder.Status.OPEN, PMWorkOrder.Status.ON_HOLD],
    ).order_by("created_at", "id")[:30]
    for order in pm_orders:
        counts["pm_work_orders"] += 1
        rows.append({
            "source_key": f"pm-work-order:{order.pk}:{order.status}",
            "kind": "TICKET_REVIEW",
            "title": f"Review PM work order #{order.pk} ({order.status})",
            "description": f"Work order: {order.title[:140]}. Review maintenance priority and next steps; no dispatch without approval.",
        })

    # This is the exported ledger model from user_accounts.models.pm_rent,
    # which uses UNPAID / PARTIAL and a stored balance rather than OPEN.
    pm_charges = PMRentCharge.objects.filter(
        business_id__in=business_ids,
        status__in=[PMRentCharge.Status.UNPAID, PMRentCharge.Status.PARTIAL],
        balance__gt=0,
        due_date__lt=timezone.localdate(),
    ).order_by("due_date", "id")[:30]
    for charge in pm_charges:
        counts["pm_rent_charges"] += 1
        rows.append({
            "source_key": f"pm-rent-charge:{charge.pk}",
            "kind": "INVOICE_REMINDER",
            "title": f"Review overdue rent charge #{charge.pk}",
            "description": f"Charge due {charge.due_date.isoformat()}. Verify assistance/abatement and ledger accuracy before drafting any reminder; never send automatically.",
        })
    return rows, counts


def discover_pilot_tasks(*, dry_run=False):
    user = get_user_model().objects.filter(email__iexact=PILOT_EMAIL, is_active=True).first()
    if not user:
        return {"pilot_found": False, "created": 0, "reason": "Pilot account absent"}
    candidates, counts = _candidates(user)
    if dry_run:
        return {"pilot_found": True, "dry_run": True, "candidates": len(candidates), "checked": counts, "created": 0}
    with transaction.atomic():
        # Serialize scans for this user across concurrent worker processes.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        prior = AuditLog.objects.filter(actor=user, action=CREATED)
        existing = {str(x) for x in prior.values_list("metadata__source_key", flat=True) if x}
        auto_total = prior.filter(metadata__origin="discovery").count()
        allowance = max(0, min(MAX_NEW_PER_RUN, MAX_TOTAL_AUTO - auto_total))
        created = 0
        for item in candidates:
            if created >= allowance:
                break
            if item["source_key"] in existing:
                continue
            AuditLog.objects.create(actor=user, action=CREATED, metadata={
                "task_id": str(uuid4()), "origin": "discovery", **item,
            })
            existing.add(item["source_key"])
            created += 1
        AuditLog.objects.create(actor=user, action=SCAN, metadata={
            "found": len(candidates), "checked": counts, "created": created, "read_only": True, "external_actions": 0,
        })
    return {"pilot_found": True, "candidates": len(candidates), "checked": counts, "created": created, "read_only": True}
