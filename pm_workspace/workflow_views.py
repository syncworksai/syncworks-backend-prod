from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .communication_models import PMConversation, PMConversationMessage
from .leasing_views import requested_workspace
from .lifecycle_models import PMOccupancy, PMTenantCase
from .models import PMUnit
from .workorder_models import PMWorkOrder


def _reference(conversation):
    return f"SW-PM-{conversation.workspace_id}-{conversation.id}"


def _make_ready_row(order):
    return {
        "id": order.id,
        "property": order.property_id,
        "property_name": order.property.name,
        "property_address": order.property.address,
        "unit": order.unit_id,
        "unit_label": order.unit.label if order.unit else "",
        "former_tenant": f"{order.tenant.first_name} {order.tenant.last_name}".strip() if order.tenant else "",
        "status": order.status,
        "priority": order.priority,
        "title": order.title,
        "description": order.description,
        "assigned_to": order.internal_assignee,
        "vendor_name": order.vendor_name,
        "scheduled_for": order.scheduled_for,
        "target_date": order.preferred_schedule,
        "estimated_cost": str(order.not_to_exceed or ""),
        "completed_at": order.completed_at,
        "resolution_notes": order.resolution_notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def evict_occupancy(request, occupancy_id):
    workspace = requested_workspace(request)
    occupancy = (
        PMOccupancy.objects.select_related("tenant", "property", "unit")
        .filter(workspace=workspace, pk=occupancy_id)
        .first()
    )
    if not occupancy:
        return Response({"detail": "Occupancy not found."}, status=status.HTTP_404_NOT_FOUND)

    tenant = occupancy.tenant
    move_out_date = request.data.get("move_out_date") or timezone.localdate()
    occupancy.status = PMOccupancy.Status.EVICTED
    occupancy.move_out_date = move_out_date
    occupancy.move_out_reason = str(request.data.get("move_out_reason") or "Eviction")
    occupancy.forwarding_address = str(request.data.get("forwarding_address") or "")
    occupancy.notes = str(request.data.get("notes") or occupancy.notes or "")
    occupancy.save()

    tenant.property_name = ""
    tenant.unit_label = ""
    tenant.status = tenant.Status.INACTIVE
    tenant.save(update_fields=["property_name", "unit_label", "status", "updated_at"])

    if occupancy.unit:
        occupancy.unit.availability = PMUnit.Availability.MAKE_READY
        occupancy.unit.available_date = None
        occupancy.unit.save(update_fields=["availability", "available_date", "updated_at"])

    balance = sum(
        entry.amount if entry.entry_type in {entry.EntryType.CHARGE, entry.EntryType.ADJUSTMENT} else -entry.amount
        for entry in tenant.ledger_entries.all()
    )
    eviction_case, created = PMTenantCase.objects.get_or_create(
        workspace=workspace,
        tenant=tenant,
        occupancy=occupancy,
        case_type=PMTenantCase.CaseType.EVICTION,
        defaults={
            "property": occupancy.property,
            "status": PMTenantCase.Status.FILED,
            "opened_date": move_out_date,
            "filed_date": request.data.get("filed_date") or move_out_date,
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
            body=f"Eviction workflow opened. Occupancy closed on {move_out_date}. Tenant balance preserved: ${balance:.2f}. Make-ready work order #{make_ready.id} created.",
        )

    return Response({
        "detail": "Tenant evicted. Eviction case, collections thread, and make-ready work order are connected.",
        "case_id": eviction_case.id,
        "case_created": created,
        "work_order_id": make_ready.id,
        "work_order_created": work_created,
        "conversation_id": thread.id,
        "tenant_balance": str(balance),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def make_ready_board(request):
    workspace = requested_workspace(request)
    qs = (
        PMWorkOrder.objects.filter(workspace=workspace, category="MAKE_READY")
        .select_related("property", "unit", "tenant")
        .order_by("completed_at", "scheduled_for", "-created_at")
    )
    selected_status = str(request.query_params.get("status") or "").upper()
    assigned_to = str(request.query_params.get("assigned_to") or "").strip()
    if selected_status:
        qs = qs.filter(status=selected_status)
    if assigned_to:
        qs = qs.filter(internal_assignee__icontains=assigned_to)
    rows = [_make_ready_row(item) for item in qs]
    return Response({
        "results": rows,
        "summary": {
            "total": len(rows),
            "unassigned": sum(1 for item in rows if not item["assigned_to"]),
            "in_progress": sum(1 for item in rows if item["status"] in {"ASSIGNED", "SCHEDULED", "IN_PROGRESS", "WAITING_PARTS", "WAITING_APPROVAL"}),
            "ready_for_final": sum(1 for item in rows if item["status"] == "COMPLETED"),
        },
    })


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_make_ready(request, work_order_id):
    workspace = requested_workspace(request)
    order = PMWorkOrder.objects.filter(workspace=workspace, pk=work_order_id, category="MAKE_READY").select_related("property", "unit", "tenant").first()
    if not order:
        return Response({"detail": "Make-ready record not found."}, status=status.HTTP_404_NOT_FOUND)
    for field in ("status", "priority", "internal_assignee", "vendor_name", "preferred_schedule", "resolution_notes"):
        if field in request.data:
            setattr(order, field, request.data.get(field) or "")
    if request.data.get("scheduled_for"):
        order.scheduled_for = request.data.get("scheduled_for")
    if request.data.get("not_to_exceed") not in (None, ""):
        order.not_to_exceed = request.data.get("not_to_exceed")
    if order.status == PMWorkOrder.Status.COMPLETED and not order.completed_at:
        order.completed_at = timezone.now()
        if order.unit:
            order.unit.availability = PMUnit.Availability.AVAILABLE
            order.unit.available_date = timezone.localdate()
            order.unit.save(update_fields=["availability", "available_date", "updated_at"])
    order.save()
    return Response(_make_ready_row(order))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def email_conversation(request, conversation_id):
    workspace = requested_workspace(request)
    conversation = PMConversation.objects.filter(workspace=workspace, pk=conversation_id).select_related("tenant", "property_owner", "property", "tenant_case").first()
    if not conversation:
        return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)
    if conversation.internal_only:
        return Response({"detail": "Internal conversations cannot be emailed."}, status=status.HTTP_400_BAD_REQUEST)

    recipient = str(request.data.get("to") or conversation.requester_email or (conversation.tenant.email if conversation.tenant else "") or (conversation.property_owner.email if conversation.property_owner else "")).strip()
    body = str(request.data.get("body") or "").strip()
    if not recipient or not body:
        return Response({"detail": "Enter a recipient email and message."}, status=status.HTTP_400_BAD_REQUEST)

    ref = _reference(conversation)
    raw_subject = str(request.data.get("subject") or conversation.subject or "SyncWorks Property Management").strip()
    subject = f"[{ref}] {raw_subject}"
    signature = str(getattr(workspace, "email_signature", "") or "").strip()
    full_body = body + (f"\n\n{signature}" if signature else "") + f"\n\nReference: {ref}\nReply to this email without changing the subject so SyncWorks can match your response to the correct record."
    from_email = str(getattr(workspace, "office_email", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "")).strip() or None
    reply_to = str(getattr(workspace, "reply_to_email", "") or getattr(workspace, "tenant_email", "") or "").strip()

    try:
        message = EmailMessage(subject=subject, body=full_body, from_email=from_email, to=[recipient], reply_to=[reply_to] if reply_to else None)
        message.send(fail_silently=False)
    except Exception as exc:
        return Response({"detail": f"Email could not be sent: {exc}"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    PMConversationMessage.objects.create(
        conversation=conversation,
        sender=request.user,
        sender_role=PMConversationMessage.SenderRole.PM,
        body=f"EMAIL TO {recipient}\nSUBJECT: {subject}\n\n{body}",
    )
    conversation.status = PMConversation.Status.WAITING_REQUESTER
    conversation.requester_email = recipient
    conversation.save(update_fields=["status", "requester_email", "updated_at"])
    return Response({"detail": "Email sent and saved to the conversation.", "reference": ref, "subject": subject, "recipient": recipient})
