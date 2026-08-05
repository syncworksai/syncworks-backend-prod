from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .communication_models import PMConversation, PMConversationMessage
from .leasing_views import requested_workspace
from .lifecycle_models import PMOccupancy, PMTenantCase
from .models import PMLedgerEntry, PMLease, PMProperty, PMTenant, PMUnit
from .owner_models import PMPropertyOwner
from .workorder_models import PMWorkOrder


def _money_balance(tenant):
    total = Decimal("0.00")
    for entry in tenant.ledger_entries.all():
        total += entry.amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -entry.amount
    return total.quantize(Decimal("0.01"))


def _occupancy_data(item):
    return {
        "id": item.id,
        "tenant": item.tenant_id,
        "tenant_name": f"{item.tenant.first_name} {item.tenant.last_name}".strip(),
        "property": item.property_id,
        "property_name": item.property.name,
        "unit": item.unit_id,
        "unit_label": item.unit.label if item.unit else "",
        "lease": item.lease_id,
        "status": item.status,
        "move_in_date": item.move_in_date,
        "notice_date": item.notice_date,
        "move_out_date": item.move_out_date,
        "move_out_reason": item.move_out_reason,
        "forwarding_address": item.forwarding_address,
        "notes": item.notes,
    }


def _case_data(item):
    return {
        "id": item.id,
        "tenant": item.tenant_id,
        "tenant_name": f"{item.tenant.first_name} {item.tenant.last_name}".strip(),
        "property": item.property_id,
        "property_name": item.property.name if item.property else "",
        "occupancy": item.occupancy_id,
        "case_type": item.case_type,
        "status": item.status,
        "opened_date": item.opened_date,
        "filed_date": item.filed_date,
        "judgment_date": item.judgment_date,
        "collections_sent_date": item.collections_sent_date,
        "agency_name": item.agency_name,
        "agency_email": item.agency_email,
        "balance_at_open": str(item.balance_at_open or "0.00"),
        "current_balance": str(item.current_balance or "0.00"),
        "reference": item.reference,
        "notes": item.notes,
    }


def _conversation_data(item):
    return {
        "id": item.id,
        "category": item.category,
        "status": item.status,
        "subject": item.subject,
        "tenant": item.tenant_id,
        "tenant_name": f"{item.tenant.first_name} {item.tenant.last_name}".strip() if item.tenant else "",
        "property": item.property_id,
        "property_name": item.property.name if item.property else "",
        "property_owner": item.property_owner_id,
        "property_owner_name": item.property_owner.name if item.property_owner else "",
        "lease": item.lease_id,
        "ledger_entry": item.ledger_entry_id,
        "work_order": item.work_order_id,
        "tenant_case": item.tenant_case_id,
        "requester_name": item.requester_name,
        "requester_email": item.requester_email,
        "internal_only": item.internal_only,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "messages": [{
            "id": message.id,
            "sender_role": message.sender_role,
            "sender_name": (message.sender.get_full_name() or message.sender.email) if message.sender else message.sender_role.title(),
            "body": message.body,
            "created_at": message.created_at,
        } for message in item.messages.all()],
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def occupancies(request):
    workspace = requested_workspace(request)
    if request.method == "GET":
        qs = PMOccupancy.objects.filter(workspace=workspace).select_related("tenant", "property", "unit", "lease")
        if request.query_params.get("tenant"):
            qs = qs.filter(tenant_id=request.query_params["tenant"])
        if request.query_params.get("property"):
            qs = qs.filter(property_id=request.query_params["property"])
        if request.query_params.get("status"):
            qs = qs.filter(status=str(request.query_params["status"]).upper())
        return Response([_occupancy_data(item) for item in qs])

    tenant = PMTenant.objects.filter(workspace=workspace, pk=request.data.get("tenant_id")).first()
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=request.data.get("property_id")).first()
    if not tenant or not property_obj:
        return Response({"detail": "Choose a valid tenant and property."}, status=status.HTTP_400_BAD_REQUEST)
    unit = PMUnit.objects.filter(workspace=workspace, property=property_obj, pk=request.data.get("unit_id")).first() if request.data.get("unit_id") else None
    lease = PMLease.objects.filter(workspace=workspace, tenant=tenant, pk=request.data.get("lease_id")).first() if request.data.get("lease_id") else tenant.leases.order_by("-start_date").first()
    PMOccupancy.objects.filter(workspace=workspace, tenant=tenant, status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN]).update(status=PMOccupancy.Status.MOVED_OUT, move_out_date=timezone.localdate(), move_out_reason="Superseded by new occupancy")
    occupancy = PMOccupancy.objects.create(
        workspace=workspace, tenant=tenant, property=property_obj, unit=unit, lease=lease,
        status=PMOccupancy.Status.ACTIVE, move_in_date=request.data.get("move_in_date") or tenant.move_in_date or timezone.localdate(),
        notes=str(request.data.get("notes") or ""), created_by=request.user,
    )
    tenant.property_name = property_obj.name
    tenant.unit_label = unit.label if unit else str(request.data.get("unit_label") or tenant.unit_label or "")
    tenant.move_in_date = occupancy.move_in_date
    tenant.status = PMTenant.Status.CONNECTED if tenant.user_id else tenant.status
    tenant.save(update_fields=["property_name", "unit_label", "move_in_date", "status", "updated_at"])
    if unit:
        unit.availability = PMUnit.Availability.OCCUPIED
        unit.save(update_fields=["availability", "updated_at"])
    return Response(_occupancy_data(occupancy), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def move_out_tenant(request, occupancy_id):
    workspace = requested_workspace(request)
    occupancy = PMOccupancy.objects.select_related("tenant", "property", "unit").filter(workspace=workspace, pk=occupancy_id).first()
    if not occupancy:
        return Response({"detail": "Occupancy not found."}, status=status.HTTP_404_NOT_FOUND)
    occupancy.status = PMOccupancy.Status.EVICTED if bool(request.data.get("evicted")) else PMOccupancy.Status.MOVED_OUT
    occupancy.move_out_date = request.data.get("move_out_date") or timezone.localdate()
    occupancy.move_out_reason = str(request.data.get("move_out_reason") or ("Eviction" if request.data.get("evicted") else "Move out"))
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
    return Response({"detail": "Occupancy closed. Tenant history and ledger were preserved.", "occupancy": _occupancy_data(occupancy), "tenant_balance": str(_money_balance(tenant))})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_cases(request):
    workspace = requested_workspace(request)
    if request.method == "GET":
        qs = PMTenantCase.objects.filter(workspace=workspace).select_related("tenant", "property", "occupancy")
        if request.query_params.get("tenant"):
            qs = qs.filter(tenant_id=request.query_params["tenant"])
        if request.query_params.get("status"):
            qs = qs.filter(status=str(request.query_params["status"]).upper())
        return Response([_case_data(item) for item in qs])
    tenant = PMTenant.objects.filter(workspace=workspace, pk=request.data.get("tenant_id")).prefetch_related("ledger_entries").first()
    if not tenant:
        return Response({"detail": "Choose a valid tenant."}, status=status.HTTP_400_BAD_REQUEST)
    occupancy = PMOccupancy.objects.filter(workspace=workspace, tenant=tenant).select_related("property").order_by("-move_in_date", "-id").first()
    balance = _money_balance(tenant)
    item = PMTenantCase.objects.create(
        workspace=workspace, tenant=tenant, property=occupancy.property if occupancy else None, occupancy=occupancy,
        case_type=str(request.data.get("case_type") or PMTenantCase.CaseType.COLLECTIONS).upper(),
        status=str(request.data.get("status") or PMTenantCase.Status.OPEN).upper(),
        opened_date=request.data.get("opened_date") or timezone.localdate(), filed_date=request.data.get("filed_date") or None,
        agency_name=str(request.data.get("agency_name") or ""), agency_email=str(request.data.get("agency_email") or ""),
        balance_at_open=request.data.get("balance_at_open") or balance, current_balance=balance,
        reference=str(request.data.get("reference") or ""), notes=str(request.data.get("notes") or ""), created_by=request.user,
    )
    return Response(_case_data(item), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_tenant_case(request, case_id):
    workspace = requested_workspace(request)
    item = PMTenantCase.objects.filter(workspace=workspace, pk=case_id).select_related("tenant", "property", "occupancy").first()
    if not item:
        return Response({"detail": "Case not found."}, status=status.HTTP_404_NOT_FOUND)
    for field in ("status", "filed_date", "judgment_date", "collections_sent_date", "agency_name", "agency_email", "reference", "notes"):
        if field in request.data:
            setattr(item, field, request.data.get(field) or (None if field.endswith("_date") else ""))
    item.current_balance = _money_balance(item.tenant)
    item.save()
    return Response(_case_data(item))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def unified_inbox(request):
    workspace = requested_workspace(request)
    if request.method == "GET":
        qs = PMConversation.objects.filter(workspace=workspace).select_related("tenant", "property", "property_owner", "lease", "ledger_entry", "work_order", "tenant_case").prefetch_related("messages", "messages__sender")
        category = str(request.query_params.get("category") or "").upper()
        if category:
            qs = qs.filter(category=category)
        search = str(request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(subject__icontains=search) | Q(requester_name__icontains=search) | Q(tenant__first_name__icontains=search) | Q(tenant__last_name__icontains=search) | Q(property__name__icontains=search))
        return Response([_conversation_data(item) for item in qs])
    category = str(request.data.get("category") or PMConversation.Category.INTERNAL).upper()
    body = str(request.data.get("body") or "").strip()
    if category not in PMConversation.Category.values or not body:
        return Response({"detail": "Choose a category and enter a message."}, status=status.HTTP_400_BAD_REQUEST)
    tenant = PMTenant.objects.filter(workspace=workspace, pk=request.data.get("tenant_id")).first() if request.data.get("tenant_id") else None
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=request.data.get("property_id")).first() if request.data.get("property_id") else None
    owner = PMPropertyOwner.objects.filter(workspace=workspace, pk=request.data.get("property_owner_id")).first() if request.data.get("property_owner_id") else None
    work_order = PMWorkOrder.objects.filter(workspace=workspace, pk=request.data.get("work_order_id")).first() if request.data.get("work_order_id") else None
    tenant_case = PMTenantCase.objects.filter(workspace=workspace, pk=request.data.get("tenant_case_id")).first() if request.data.get("tenant_case_id") else None
    item = PMConversation.objects.create(
        workspace=workspace, category=category, status=PMConversation.Status.WAITING_REQUESTER,
        subject=str(request.data.get("subject") or "New conversation"), tenant=tenant, property=property_obj,
        property_owner=owner, work_order=work_order, tenant_case=tenant_case,
        requester_name=(f"{tenant.first_name} {tenant.last_name}".strip() if tenant else owner.name if owner else "Internal team"),
        requester_email=(tenant.email if tenant else owner.email if owner else ""), internal_only=category == PMConversation.Category.INTERNAL,
        created_by=request.user,
    )
    PMConversationMessage.objects.create(conversation=item, sender=request.user, sender_role=PMConversationMessage.SenderRole.INTERNAL if item.internal_only else PMConversationMessage.SenderRole.PM, body=body)
    item = PMConversation.objects.select_related("tenant", "property", "property_owner", "lease", "ledger_entry", "work_order", "tenant_case").prefetch_related("messages", "messages__sender").get(pk=item.pk)
    return Response(_conversation_data(item), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def inbox_reply(request, conversation_id):
    workspace = requested_workspace(request)
    item = PMConversation.objects.filter(workspace=workspace, pk=conversation_id).first()
    if not item:
        return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)
    body = str(request.data.get("body") or "").strip()
    if not body:
        return Response({"detail": "Enter a reply."}, status=status.HTTP_400_BAD_REQUEST)
    role = PMConversationMessage.SenderRole.INTERNAL if item.internal_only else PMConversationMessage.SenderRole.PM
    PMConversationMessage.objects.create(conversation=item, sender=request.user, sender_role=role, body=body)
    item.status = PMConversation.Status.WAITING_REQUESTER
    item.save(update_fields=["status", "updated_at"])
    return Response({"detail": "Reply sent."})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tenant_portal_communications(request):
    tenant = PMTenant.objects.filter(user=request.user).order_by("-updated_at").first()
    if not tenant:
        return Response({"detail": "No tenant profile is connected to this account."}, status=status.HTTP_404_NOT_FOUND)
    occupancy = PMOccupancy.objects.filter(tenant=tenant, status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN]).select_related("property", "unit").first()
    if request.method == "GET":
        conversations = PMConversation.objects.filter(tenant=tenant, internal_only=False).select_related("property", "work_order").prefetch_related("messages", "messages__sender")
        work_orders = PMWorkOrder.objects.filter(tenant=tenant).select_related("property", "unit")
        return Response({
            "tenant": {"id": tenant.id, "name": f"{tenant.first_name} {tenant.last_name}".strip()},
            "occupancy": _occupancy_data(occupancy) if occupancy else None,
            "conversations": [_conversation_data(item) for item in conversations],
            "maintenance": [{"id": item.id, "property_name": item.property.name, "title": item.title, "category": item.category, "priority": item.priority, "status": item.status, "description": item.description, "created_at": item.created_at} for item in work_orders],
        })
    action = str(request.data.get("action") or "MESSAGE").upper()
    body = str(request.data.get("body") or request.data.get("description") or "").strip()
    if not body:
        return Response({"detail": "Enter details."}, status=status.HTTP_400_BAD_REQUEST)
    if action == "MAINTENANCE":
        if not occupancy:
            return Response({"detail": "No active property occupancy is connected to this tenant."}, status=status.HTTP_400_BAD_REQUEST)
        order = PMWorkOrder.objects.create(
            workspace=tenant.workspace, property=occupancy.property, unit=occupancy.unit, tenant=tenant,
            source=PMWorkOrder.Source.TENANT_PORTAL, category=str(request.data.get("category") or "GENERAL"),
            issue_type=str(request.data.get("issue_type") or ""), title=str(request.data.get("subject") or "Tenant maintenance request"),
            description=body, priority=str(request.data.get("priority") or PMWorkOrder.Priority.ROUTINE).upper(),
            caller_name=f"{tenant.first_name} {tenant.last_name}".strip(), caller_phone=tenant.phone,
            permission_to_enter=bool(request.data.get("permission_to_enter")), pets_or_access_notes=str(request.data.get("access_notes") or ""), created_by=request.user,
        )
        conversation = PMConversation.objects.create(
            workspace=tenant.workspace, category=PMConversation.Category.MAINTENANCE, status=PMConversation.Status.WAITING_PM,
            subject=order.title, tenant=tenant, property=occupancy.property, work_order=order,
            requester_name=f"{tenant.first_name} {tenant.last_name}".strip(), requester_email=tenant.email, created_by=request.user,
        )
        PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=PMConversationMessage.SenderRole.TENANT, body=body)
        return Response({"detail": "Maintenance request sent.", "work_order_id": order.id, "conversation_id": conversation.id}, status=status.HTTP_201_CREATED)
    conversation = PMConversation.objects.create(
        workspace=tenant.workspace, category=PMConversation.Category.TENANT, status=PMConversation.Status.WAITING_PM,
        subject=str(request.data.get("subject") or "Tenant message"), tenant=tenant, property=occupancy.property if occupancy else None,
        requester_name=f"{tenant.first_name} {tenant.last_name}".strip(), requester_email=tenant.email, created_by=request.user,
    )
    PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=PMConversationMessage.SenderRole.TENANT, body=body)
    return Response({"detail": "Message sent.", "conversation_id": conversation.id}, status=status.HTTP_201_CREATED)
