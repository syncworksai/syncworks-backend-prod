from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _tenant_account
from .communication_models import PMConversation, PMConversationMessage
from .models import PMLedgerEntry, PMProperty, PMTenant, PMWorkspace
from .owner_models import PMPropertyOwner


def _workspace(request):
    workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
    if not workspace_id and isinstance(request.data, dict):
        workspace_id = request.data.get("workspace_id")
    qs = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    workspace = qs.filter(pk=workspace_id).first() if workspace_id else qs.order_by("id").first()
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


def _entry_data(entry):
    return {
        "id": entry.id,
        "tenant": entry.tenant_id,
        "tenant_name": f"{entry.tenant.first_name} {entry.tenant.last_name}".strip(),
        "entry_date": entry.entry_date,
        "entry_type": entry.entry_type,
        "amount": str(entry.amount),
        "category": entry.category,
        "payment_method": entry.payment_method,
        "reference": entry.reference,
        "memo": entry.memo,
    }


def _conversation_data(conversation):
    entry = conversation.ledger_entry
    return {
        "id": conversation.id,
        "category": conversation.category,
        "status": conversation.status,
        "subject": conversation.subject,
        "requester_name": conversation.requester_name,
        "requester_email": conversation.requester_email,
        "tenant_id": conversation.tenant_id,
        "tenant_name": f"{conversation.tenant.first_name} {conversation.tenant.last_name}".strip() if conversation.tenant else "",
        "property_owner_id": conversation.property_owner_id,
        "property_owner_name": conversation.property_owner.name if conversation.property_owner else "",
        "ledger_entry": _entry_data(entry) if entry else None,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": [
            {
                "id": message.id,
                "sender_role": message.sender_role,
                "sender_name": (message.sender.get_full_name() or message.sender.email) if message.sender else message.sender_role.title(),
                "body": message.body,
                "created_at": message.created_at,
            }
            for message in conversation.messages.all()
        ],
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def bulk_delete_ledger(request):
    workspace = _workspace(request)
    raw_ids = request.data.get("ids") if isinstance(request.data, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return Response({"detail": "Select at least one ledger item."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        ids = sorted({int(value) for value in raw_ids})
    except (TypeError, ValueError):
        return Response({"detail": "Ledger item IDs must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
    qs = PMLedgerEntry.objects.filter(workspace=workspace, id__in=ids)
    deleted_ids = list(qs.values_list("id", flat=True))
    qs.delete()
    return Response({"detail": f"Deleted {len(deleted_ids)} ledger item(s).", "deleted_ids": deleted_ids})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def pm_conversations(request):
    workspace = _workspace(request)
    if request.method == "GET":
        qs = PMConversation.objects.filter(workspace=workspace).select_related("tenant", "property_owner", "ledger_entry", "ledger_entry__tenant").prefetch_related("messages", "messages__sender")
        category = str(request.query_params.get("category") or "").upper()
        conversation_status = str(request.query_params.get("status") or "").upper()
        if category:
            qs = qs.filter(category=category)
        if conversation_status:
            qs = qs.filter(status=conversation_status)
        return Response([_conversation_data(item) for item in qs])

    category = str(request.data.get("category") or "TENANT").upper()
    if category not in PMConversation.Category.values:
        return Response({"category": "Choose TENANT, INVESTOR, or MAINTENANCE."}, status=status.HTTP_400_BAD_REQUEST)
    subject = str(request.data.get("subject") or "New conversation").strip()
    body = str(request.data.get("body") or "").strip()
    if not body:
        return Response({"body": "Enter a message."}, status=status.HTTP_400_BAD_REQUEST)
    tenant = PMTenant.objects.filter(workspace=workspace, pk=request.data.get("tenant_id")).first() if request.data.get("tenant_id") else None
    owner = PMPropertyOwner.objects.filter(workspace=workspace, pk=request.data.get("property_owner_id")).first() if request.data.get("property_owner_id") else None
    conversation = PMConversation.objects.create(
        workspace=workspace,
        category=category,
        status=PMConversation.Status.WAITING_REQUESTER,
        subject=subject,
        tenant=tenant,
        property_owner=owner,
        requester_name=(f"{tenant.first_name} {tenant.last_name}".strip() if tenant else owner.name if owner else ""),
        requester_email=(tenant.email if tenant else owner.email if owner else ""),
        created_by=request.user,
    )
    PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=PMConversationMessage.SenderRole.PM, body=body)
    return Response(_conversation_data(conversation), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reply_conversation(request, conversation_id):
    workspace = _workspace(request)
    conversation = PMConversation.objects.filter(workspace=workspace, pk=conversation_id).first()
    if not conversation:
        return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)
    body = str(request.data.get("body") or "").strip()
    if not body:
        return Response({"body": "Enter a reply."}, status=status.HTTP_400_BAD_REQUEST)
    PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=PMConversationMessage.SenderRole.PM, body=body)
    conversation.status = PMConversation.Status.WAITING_REQUESTER
    conversation.save(update_fields=["status", "updated_at"])
    conversation = PMConversation.objects.select_related("tenant", "property_owner", "ledger_entry", "ledger_entry__tenant").prefetch_related("messages", "messages__sender").get(pk=conversation.id)
    return Response(_conversation_data(conversation))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resolve_conversation(request, conversation_id):
    workspace = _workspace(request)
    conversation = PMConversation.objects.filter(workspace=workspace, pk=conversation_id).first()
    if not conversation:
        return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)
    conversation.status = PMConversation.Status.RESOLVED
    conversation.save(update_fields=["status", "updated_at"])
    return Response({"detail": "Conversation resolved.", "id": conversation.id, "status": conversation.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_ledger_information(request, entry_id):
    entry = PMLedgerEntry.objects.select_related("tenant", "workspace").filter(pk=entry_id).first()
    if not entry:
        return Response({"detail": "Ledger item not found."}, status=status.HTTP_404_NOT_FOUND)
    tenant = PMTenant.objects.filter(pk=entry.tenant_id, user=request.user, status=PMTenant.Status.CONNECTED).first()
    owner = None
    sender_role = PMConversationMessage.SenderRole.TENANT
    category = PMConversation.Category.TENANT
    if not tenant:
        owner = PMPropertyOwner.objects.filter(workspace=entry.workspace, email__iexact=request.user.email).first()
        if not owner:
            return Response({"detail": "You do not have access to this ledger item."}, status=status.HTTP_403_FORBIDDEN)
        labels = set(owner.properties.values_list("name", flat=True)) | set(owner.properties.values_list("address", flat=True))
        if entry.tenant.property_name not in labels:
            return Response({"detail": "This ledger item is not attached to one of your properties."}, status=status.HTTP_403_FORBIDDEN)
        sender_role = PMConversationMessage.SenderRole.INVESTOR
        category = PMConversation.Category.INVESTOR
    body = str(request.data.get("body") or "Please provide more information about this ledger item.").strip()
    conversation = PMConversation.objects.create(
        workspace=entry.workspace,
        category=category,
        status=PMConversation.Status.WAITING_PM,
        subject=f"Ledger question: {entry.category.replace('_', ' ').title()} on {entry.entry_date}",
        tenant=entry.tenant if tenant else None,
        property_owner=owner,
        ledger_entry=entry,
        requester_name=(f"{entry.tenant.first_name} {entry.tenant.last_name}".strip() if tenant else owner.name),
        requester_email=(entry.tenant.email if tenant else owner.email),
        created_by=request.user,
    )
    PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=sender_role, body=body)
    return Response({"detail": "Your question was sent to the property management company.", "conversation": _conversation_data(conversation)}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_conversations(request):
    tenant = PMTenant.objects.filter(user=request.user, status=PMTenant.Status.CONNECTED).first()
    owner = PMPropertyOwner.objects.filter(email__iexact=request.user.email).first()
    qs = PMConversation.objects.none()
    if tenant:
        qs = PMConversation.objects.filter(tenant=tenant)
    elif owner:
        qs = PMConversation.objects.filter(property_owner=owner)
    qs = qs.select_related("tenant", "property_owner", "ledger_entry", "ledger_entry__tenant").prefetch_related("messages", "messages__sender")
    return Response([_conversation_data(item) for item in qs])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def requester_reply(request, conversation_id):
    tenant = PMTenant.objects.filter(user=request.user, status=PMTenant.Status.CONNECTED).first()
    owner = PMPropertyOwner.objects.filter(email__iexact=request.user.email).first()
    conversation = PMConversation.objects.filter(pk=conversation_id).first()
    allowed = conversation and ((tenant and conversation.tenant_id == tenant.id) or (owner and conversation.property_owner_id == owner.id))
    if not allowed:
        return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)
    body = str(request.data.get("body") or "").strip()
    if not body:
        return Response({"body": "Enter a reply."}, status=status.HTTP_400_BAD_REQUEST)
    role = PMConversationMessage.SenderRole.TENANT if tenant else PMConversationMessage.SenderRole.INVESTOR
    PMConversationMessage.objects.create(conversation=conversation, sender=request.user, sender_role=role, body=body)
    conversation.status = PMConversation.Status.WAITING_PM
    conversation.save(update_fields=["status", "updated_at"])
    return Response({"detail": "Reply sent."})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def investor_ledger(request):
    owners = PMPropertyOwner.objects.filter(email__iexact=request.user.email).prefetch_related("properties")
    if not owners.exists():
        return Response({"detail": "No investor ownership profile is linked to this email."}, status=status.HTTP_404_NOT_FOUND)
    property_labels = set()
    owner_names = []
    for owner in owners:
        owner_names.append(owner.name)
        property_labels.update(owner.properties.values_list("name", flat=True))
        property_labels.update(owner.properties.values_list("address", flat=True))
    tenants = PMTenant.objects.filter(property_name__in=property_labels).prefetch_related("ledger_entries", "leases", "document_packets")
    entries = PMLedgerEntry.objects.filter(tenant__in=tenants).select_related("tenant").order_by("-entry_date", "-id")
    total = sum((entry.amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -entry.amount for entry in entries), Decimal("0.00"))
    return Response({
        "owner_names": owner_names,
        "properties": sorted(property_labels),
        "balance": str(total.quantize(Decimal("0.01"))),
        "accounts": [_tenant_account(tenant) for tenant in tenants],
        "ledger": [_entry_data(entry) for entry in entries[:500]],
    })
