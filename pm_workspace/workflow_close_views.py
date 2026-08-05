from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .communication_models import PMConversation, PMConversationMessage
from .leasing_views import requested_workspace
from .lifecycle_models import PMOccupancy, PMTenantCase
from .models import PMTenant, PMUnit
from .record_views import _money_balance, _occupancy_data
from .workorder_models import PMWorkOrder


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def close_occupancy_workflow(request, occupancy_id):
    workspace = requested_workspace(request)
    occupancy = PMOccupancy.objects.select_related("tenant", "property", "unit").filter(workspace=workspace, pk=occupancy_id).first()
    if not occupancy:
        return Response({"detail": "Occupancy not found."}, status=status.HTTP_404_NOT_FOUND)

    evicted = bool(request.data.get("evicted"))
    occupancy.status = PMOccupancy.Status.EVICTED if evicted else PMOccupancy.Status.MOVED_OUT
    occupancy.move_out_date = request.data.get("move_out_date") or timezone.localdate()
    occupancy.move_out_reason = str(request.data.get("move_out_reason") or ("Eviction" if evicted else "Tenant moved out"))
    occupancy.forwarding_address = str(request.data.get("forwarding_address") or "")
    occupancy.notes = str(request.data.get("notes") or occupancy.notes or "")
    occupancy.save()

    tenant = occupancy.tenant
    tenant.property_name = ""
    tenant.unit_label = ""
    tenant.status = PMTenant.Status.INACTIVE
    tenant.save(update_fields=["property_name", "unit_label", "status", "updated_at"])

    if occupancy.unit:
        occupancy.unit.availability = PMUnit.Availability.MAKE_READY
        occupancy.unit.available_date = None
        occupancy.unit.save(update_fields=["availability", "available_date", "updated_at"])

    balance = _money_balance(tenant)
    response = {
        "detail": "Occupancy closed. Tenant history and ledger were preserved.",
        "occupancy": _occupancy_data(occupancy),
        "tenant_balance": str(balance),
    }

    if not evicted:
        return Response(response)

    eviction_case, case_created = PMTenantCase.objects.get_or_create(
        workspace=workspace,
        tenant=tenant,
        occupancy=occupancy,
        case_type=PMTenantCase.CaseType.EVICTION,
        defaults={
            "property": occupancy.property,
            "status": PMTenantCase.Status.FILED,
            "opened_date": occupancy.move_out_date,
            "filed_date": request.data.get("filed_date") or occupancy.move_out_date,
            "balance_at_open": balance,
            "current_balance": balance,
            "reference": str(request.data.get("reference") or f"EVICTION-{occupancy.id}"),
            "notes": str(request.data.get("case_notes") or occupancy.notes or "Automatically created from eviction workflow."),
            "created_by": request.user,
        },
    )

    make_ready, work_created = PMWorkOrder.objects.get_or_create(
        workspace=workspace,
        property=occupancy.property,
        unit=occupancy.unit,
        tenant=tenant,
        category="MAKE_READY",
        defaults={
            "source": PMWorkOrder.Source.OFFICE,
            "title": f"Make ready: {occupancy.property.name}{' · ' + occupancy.unit.label if occupancy.unit else ''}",
            "description": "Complete move-out assessment, repairs, cleaning, safety checks, final inspection, and listing readiness.",
            "priority": PMWorkOrder.Priority.HIGH,
            "status": PMWorkOrder.Status.NEW,
            "dispatch_mode": PMWorkOrder.Dispatch.UNASSIGNED,
            "preferred_schedule": str(request.data.get("target_date") or ""),
            "internal_assignee": str(request.data.get("assigned_to") or ""),
            "created_by": request.user,
        },
    )

    thread, thread_created = PMConversation.objects.get_or_create(
        workspace=workspace,
        category=PMConversation.Category.COLLECTIONS,
        tenant=tenant,
        property=occupancy.property,
        tenant_case=eviction_case,
        defaults={
            "status": PMConversation.Status.OPEN,
            "subject": f"Eviction case · {tenant.first_name} {tenant.last_name} · {occupancy.property.name}",
            "requester_name": f"{tenant.first_name} {tenant.last_name}".strip(),
            "requester_email": tenant.email,
            "created_by": request.user,
        },
    )
    if thread_created:
        PMConversationMessage.objects.create(
            conversation=thread,
            sender=request.user,
            sender_role=PMConversationMessage.SenderRole.SYSTEM,
            body=f"Eviction workflow opened. Occupancy closed on {occupancy.move_out_date}. Tenant balance preserved: ${balance:.2f}. Make-ready work order #{make_ready.id} created.",
        )

    response.update({
        "detail": "Tenant evicted. Eviction case, collections thread, and make-ready work order were created.",
        "case_id": eviction_case.id,
        "case_created": case_created,
        "work_order_id": make_ready.id,
        "work_order_created": work_created,
        "conversation_id": thread.id,
    })
    return Response(response)
