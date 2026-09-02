from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from personal_calendar.connection_store import list_connections

from .communication_models import PMConversation
from .document_models import PMPropertyDocument
from .lead_models import PMLead
from .lifecycle_models import PMTenantCase
from .models import PMDocumentPacket, PMLedgerEntry, PMLease, PMProject, PMProperty, PMUnit
from .views import _requested_workspace
from .workorder_models import PMWorkOrder


OPEN_WORK_ORDER_STATUSES = [
    PMWorkOrder.Status.NEW,
    PMWorkOrder.Status.TRIAGE,
    PMWorkOrder.Status.ASSIGNED,
    PMWorkOrder.Status.MARKETPLACE,
    PMWorkOrder.Status.SCHEDULED,
    PMWorkOrder.Status.IN_PROGRESS,
    PMWorkOrder.Status.WAITING_PARTS,
    PMWorkOrder.Status.WAITING_APPROVAL,
]
ACTIVE_PROJECT_STATUSES = [
    PMProject.Status.REQUESTED,
    PMProject.Status.PLANNING,
    PMProject.Status.APPROVAL,
    PMProject.Status.SCHEDULED,
    PMProject.Status.IN_PROGRESS,
    PMProject.Status.REVIEW,
]
OPEN_CASE_STATUSES = [value for value, _label in PMTenantCase.Status.choices if value != PMTenantCase.Status.CLOSED]


def _money(value):
    return str((value or Decimal("0.00")).quantize(Decimal("0.01")))


def _month_start(value):
    return date(value.year, value.month, 1)


def _shift_month(value, delta):
    month_index = value.year * 12 + value.month - 1 + delta
    return date(month_index // 12, month_index % 12 + 1, 1)


def _financials(workspace, today):
    first_month = _shift_month(_month_start(today), -5)
    ledger = PMLedgerEntry.objects.filter(workspace=workspace)
    totals = ledger.aggregate(
        charges=Sum("amount", filter=Q(entry_type__in=[PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT])),
        payments=Sum("amount", filter=Q(entry_type=PMLedgerEntry.EntryType.PAYMENT)),
        credits=Sum("amount", filter=Q(entry_type=PMLedgerEntry.EntryType.CREDIT)),
    )
    outstanding = (totals["charges"] or Decimal("0.00")) - (totals["payments"] or Decimal("0.00")) - (totals["credits"] or Decimal("0.00"))

    buckets = {}
    for offset in range(6):
        start = _shift_month(first_month, offset)
        buckets[(start.year, start.month)] = {"month": start.strftime("%b"), "month_key": start.strftime("%Y-%m"), "charges": Decimal("0.00"), "payments": Decimal("0.00")}
    for entry in ledger.filter(entry_date__gte=first_month).only("entry_date", "entry_type", "amount"):
        bucket = buckets.get((entry.entry_date.year, entry.entry_date.month))
        if not bucket:
            continue
        if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT}:
            bucket["charges"] += entry.amount
        elif entry.entry_type == PMLedgerEntry.EntryType.PAYMENT:
            bucket["payments"] += entry.amount

    monthly = []
    for bucket in buckets.values():
        monthly.append({**bucket, "charges": _money(bucket["charges"]), "payments": _money(bucket["payments"])})
    current = monthly[-1]
    current_charges = Decimal(current["charges"])
    current_payments = Decimal(current["payments"])
    collection_rate = round(float(current_payments / current_charges * 100), 1) if current_charges > 0 else 0
    housing_payments = ledger.filter(
        entry_date__gte=_month_start(today),
        entry_type=PMLedgerEntry.EntryType.PAYMENT,
        payment_method=PMLedgerEntry.Method.HOUSING_AUTHORITY,
    ).aggregate(total=Sum("amount"))["total"]
    return {
        "month_revenue": _money(current_payments),
        "month_charges": _money(current_charges),
        "collection_rate": collection_rate,
        "outstanding_balance": _money(max(outstanding, Decimal("0.00"))),
        "housing_payments": _money(housing_payments),
        "monthly": monthly,
    }


def _schedule(workspace, today):
    end_date = today + timedelta(days=7)
    items = []
    work_orders = PMWorkOrder.objects.filter(
        workspace=workspace,
        status__in=OPEN_WORK_ORDER_STATUSES,
        scheduled_for__date__gte=today,
        scheduled_for__date__lte=end_date,
    ).select_related("property", "unit")
    for item in work_orders:
        items.append({
            "id": f"work-order-{item.id}",
            "type": "WORK_ORDER",
            "title": item.title,
            "subtitle": " · ".join(filter(None, [item.property.name, item.unit.label if item.unit else "", item.get_status_display()])),
            "date": timezone.localtime(item.scheduled_for).date().isoformat(),
            "datetime": timezone.localtime(item.scheduled_for).isoformat(),
            "status": item.status,
            "href": f"/pm/work-orders?property={item.property_id}",
        })

    projects = PMProject.objects.filter(workspace=workspace, status__in=ACTIVE_PROJECT_STATUSES).select_related("property")
    projects = projects.filter(Q(target_date__range=(today, end_date)) | Q(next_action_due__range=(today, end_date)))
    for item in projects:
        due_options = [value for value in [item.next_action_due, item.target_date] if value and today <= value <= end_date]
        due = min(due_options)
        items.append({
            "id": f"project-{item.id}",
            "type": "PROJECT",
            "title": item.next_action or item.title,
            "subtitle": " · ".join(filter(None, [item.title if item.next_action else "", item.property.name if item.property else "", item.get_status_display()])),
            "date": due.isoformat(),
            "datetime": "",
            "status": item.status,
            "href": "/pm/projects",
        })

    leases = PMLease.objects.filter(workspace=workspace, end_date__range=(today, end_date)).exclude(status="ENDED").select_related("tenant", "unit__property")
    for item in leases:
        tenant_name = f"{item.tenant.first_name} {item.tenant.last_name}".strip()
        items.append({
            "id": f"lease-{item.id}",
            "type": "LEASE",
            "title": f"Lease expires · {tenant_name}",
            "subtitle": item.unit.property.name if item.unit else "Tenant record",
            "date": item.end_date.isoformat(),
            "datetime": "",
            "status": item.status,
            "href": "/pm/tenants",
        })

    documents = PMPropertyDocument.objects.filter(
        workspace=workspace,
        expiration_date__range=(today, end_date),
    ).exclude(status__in=[PMPropertyDocument.Status.ARCHIVED, PMPropertyDocument.Status.EXPIRED]).select_related("property")
    for item in documents:
        items.append({
            "id": f"document-{item.id}",
            "type": "DOCUMENT",
            "title": f"Document expires · {item.title}",
            "subtitle": item.property.name,
            "date": item.expiration_date.isoformat(),
            "datetime": "",
            "status": item.status,
            "href": f"/pm/properties/{item.property_id}?tab=documents",
        })

    items.sort(key=lambda item: (item["date"], item["datetime"] or "", item["title"]))
    return {
        "today_count": sum(1 for item in items if item["date"] == today.isoformat()),
        "week_count": len(items),
        "items": items[:10],
    }


def _email_status(user, workspace):
    microsoft = [row for row in list_connections(user) if row.get("provider") == "MICROSOFT" and row.get("credential_data") and row.get("enabled", True)]
    routed = [
        row for row in microsoft
        if row.get("mail_enabled")
        and "PM" in (row.get("mail_destinations") or [])
        and workspace.id in [int(value) for value in row.get("pm_workspace_ids") or [] if str(value).isdigit()]
    ]
    most_recent = max((str(row.get("mail_last_synced_at") or "") for row in routed), default="")
    first_error = next((str(row.get("mail_last_error") or "") for row in routed if row.get("mail_last_error")), "")
    return {
        "microsoft_connected": bool(microsoft),
        "pm_routing_enabled": bool(routed),
        "account_count": len(routed),
        "last_synced_at": most_recent or None,
        "last_error": first_error,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def command_center(request):
    workspace = _requested_workspace(request)
    today = timezone.localdate()

    properties = PMProperty.objects.filter(workspace=workspace).annotate(
        total_units=Count("units", distinct=True),
        occupied_units=Count("units", filter=Q(units__availability=PMUnit.Availability.OCCUPIED), distinct=True),
    )
    total_units = sum(item.total_units for item in properties)
    occupied_units = sum(item.occupied_units for item in properties)
    occupancy_rate = round(occupied_units / total_units * 100) if total_units else 0

    open_orders = PMWorkOrder.objects.filter(workspace=workspace, status__in=OPEN_WORK_ORDER_STATUSES).select_related("property", "unit")
    active_projects = PMProject.objects.filter(workspace=workspace, status__in=ACTIVE_PROJECT_STATUSES)
    open_cases = PMTenantCase.objects.filter(workspace=workspace, status__in=OPEN_CASE_STATUSES).select_related("tenant", "property")
    active_leads = PMLead.objects.filter(workspace=workspace).exclude(stage__in=[PMLead.Stage.WON, PMLead.Stage.LOST])
    waiting_pm = PMConversation.objects.filter(workspace=workspace, status=PMConversation.Status.WAITING_PM)

    section8_leases = PMLease.objects.filter(workspace=workspace, section8=True).exclude(status="ENDED")
    section8_packets = PMDocumentPacket.objects.filter(workspace=workspace).filter(Q(packet_type__icontains="SECTION8") | ~Q(housing_authority="")).exclude(status__in=[PMDocumentPacket.Status.COMPLETED, PMDocumentPacket.Status.VOID])
    section8_documents = PMPropertyDocument.objects.filter(workspace=workspace, category=PMPropertyDocument.Category.SECTION8).filter(status__in=[PMPropertyDocument.Status.DRAFT, PMPropertyDocument.Status.PENDING_SIGNATURE, PMPropertyDocument.Status.SUBMITTED])
    section8_waiting = PMConversation.objects.filter(workspace=workspace, status=PMConversation.Status.WAITING_REQUESTER).filter(Q(subject__icontains="section 8") | Q(subject__icontains="housing"))
    section8_attention = section8_packets.count() + section8_documents.count() + section8_waiting.count()

    overdue_projects = active_projects.filter(Q(target_date__lt=today) | Q(next_action_due__lt=today)).distinct()
    blocked_projects = active_projects.exclude(blocker="")
    urgent_orders = open_orders.filter(priority__in=[PMWorkOrder.Priority.URGENT, PMWorkOrder.Priority.EMERGENCY])
    collection_cases = open_cases.filter(case_type=PMTenantCase.CaseType.COLLECTIONS)
    eviction_cases = open_cases.filter(case_type=PMTenantCase.CaseType.EVICTION)
    make_ready = open_orders.filter(category="MAKE_READY")
    at_risk = properties.filter(status=PMProperty.Status.AT_RISK)

    health_score = max(0, 100 - at_risk.count() * 12 - urgent_orders.count() * 5 - blocked_projects.count() * 6 - open_cases.count() * 3)
    attention = [
        {"key": "urgent-work-orders", "label": "Urgent work orders", "count": urgent_orders.count(), "detail": "Emergency and urgent maintenance", "tone": "rose", "href": "/pm/work-orders?filter=URGENT"},
        {"key": "collections", "label": "Collections", "count": collection_cases.count(), "detail": "Open collection cases", "tone": "amber", "href": "/pm/settings?view=messages&tab=occupancy&case=collections"},
        {"key": "evictions", "label": "Evictions", "count": eviction_cases.count(), "detail": "Open eviction workflows", "tone": "rose", "href": "/pm/settings?view=messages&tab=occupancy&case=evictions"},
        {"key": "section8", "label": "Section 8 follow-up", "count": section8_attention, "detail": "Packets, documents, and replies waiting", "tone": "violet", "href": "/pm/leasing?focus=section8"},
        {"key": "projects", "label": "Overdue projects", "count": overdue_projects.count(), "detail": "Target or next action is overdue", "tone": "amber", "href": "/pm/projects"},
        {"key": "messages", "label": "Waiting on your team", "count": waiting_pm.count(), "detail": "PM conversations need a response", "tone": "cyan", "href": "/pm/settings?view=messages"},
    ]

    priority = {PMWorkOrder.Priority.EMERGENCY: 0, PMWorkOrder.Priority.URGENT: 1, PMWorkOrder.Priority.HIGH: 2, PMWorkOrder.Priority.ROUTINE: 3}
    order_rows = sorted(list(open_orders[:100]), key=lambda item: (priority.get(item.priority, 9), item.scheduled_for or timezone.now(), -item.id))[:6]
    active_order_rows = [{
        "id": item.id,
        "title": item.title,
        "property_name": item.property.name,
        "unit_label": item.unit.label if item.unit else "",
        "priority": item.priority,
        "status": item.status,
        "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for else None,
        "href": f"/pm/work-orders?property={item.property_id}",
    } for item in order_rows]

    property_rows = [{
        "id": item.id,
        "name": item.name,
        "address": ", ".join(filter(None, [item.address, item.city, item.state])),
        "status": item.status,
        "total_units": item.total_units,
        "occupied_units": item.occupied_units,
        "occupancy_rate": round(item.occupied_units / item.total_units * 100) if item.total_units else 0,
        "href": f"/pm/properties/{item.id}",
    } for item in properties.order_by("name")[:6]]

    financials = _financials(workspace, today)
    return Response({
        "generated_at": timezone.now().isoformat(),
        "workspace": {"id": workspace.id, "name": workspace.name},
        "health": {"score": health_score, "label": "Needs attention" if health_score < 85 else "Performing well"},
        "kpis": {
            "properties": properties.count(),
            "units": total_units,
            "occupied_units": occupied_units,
            "occupancy_rate": occupancy_rate,
            "at_risk": at_risk.count(),
            "open_work_orders": open_orders.count(),
            "make_ready": make_ready.count(),
            "active_projects": active_projects.count(),
            "blocked_projects": blocked_projects.count(),
            "active_leads": active_leads.count(),
        },
        "financials": financials,
        "cases": {
            "open": open_cases.count(),
            "collections": collection_cases.count(),
            "evictions": eviction_cases.count(),
            "payment_plans": open_cases.filter(case_type=PMTenantCase.CaseType.PAYMENT_PLAN).count(),
        },
        "section8": {
            "active_leases": section8_leases.count(),
            "pending_packets": section8_packets.count(),
            "pending_documents": section8_documents.count(),
            "waiting_responses": section8_waiting.count(),
            "attention": section8_attention,
        },
        "email": _email_status(request.user, workspace),
        "schedule": _schedule(workspace, today),
        "attention": attention,
        "active_work_orders": active_order_rows,
        "properties": property_rows,
        "documents": {
            "ownership_records": PMPropertyDocument.objects.filter(workspace=workspace, category=PMPropertyDocument.Category.OWNERSHIP).count(),
            "pending": PMPropertyDocument.objects.filter(workspace=workspace, status__in=[PMPropertyDocument.Status.DRAFT, PMPropertyDocument.Status.PENDING_SIGNATURE, PMPropertyDocument.Status.SUBMITTED]).count(),
        },
    })
