from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from personal_calendar.connection_store import find_connection
from personal_calendar.mail_service import send_microsoft_mail
from personal_calendar.sync_service import connection_access_token

from .lead_models import PMLead, PMLeadMessage
from .leasing_views import requested_workspace
from .models import PMProperty, PMTenant


LEAD_TYPES = {value for value, _ in PMLead.LeadType.choices}
LEAD_SOURCES = {value for value, _ in PMLead.Source.choices}
LEAD_STAGES = {value for value, _ in PMLead.Stage.choices}


def _money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _lead_data(item, include_messages=False):
    data = {
        "id": item.id,
        "stage": item.stage,
        "lead_type": item.lead_type,
        "source": item.source,
        "source_label": item.source_label or item.get_source_display(),
        "first_name": item.first_name,
        "last_name": item.last_name,
        "full_name": item.full_name,
        "email": item.email,
        "phone": item.phone,
        "company_name": item.company_name,
        "property": item.property_id,
        "property_name": item.property.name if item.property else "",
        "requested_start": item.requested_start,
        "requested_end": item.requested_end,
        "adults": item.adults,
        "children": item.children,
        "pets": item.pets,
        "pet_notes": item.pet_notes,
        "furnished_requested": item.furnished_requested,
        "budget_amount": str(item.budget_amount) if item.budget_amount is not None else None,
        "summary": item.summary,
        "notes": item.notes,
        "classification_confidence": item.classification_confidence,
        "classification_reason": item.classification_reason,
        "mailbox_connection_id": item.mailbox_connection_id,
        "external_thread_id": item.external_thread_id,
        "source_subject": item.source_subject,
        "metadata": item.metadata or {},
        "assigned_to": item.assigned_to_id,
        "assigned_to_name": (item.assigned_to.get_full_name() or item.assigned_to.email) if item.assigned_to else "",
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "message_count": item.messages.count(),
        "last_message_at": item.messages.order_by("-created_at").values_list("created_at", flat=True).first(),
    }
    if include_messages:
        data["messages"] = [{
            "id": message.id,
            "direction": message.direction,
            "channel": message.channel,
            "sender_name": message.sender_name,
            "sender_email": message.sender_email,
            "recipient_email": message.recipient_email,
            "subject": message.subject,
            "body": message.body,
            "external_message_id": message.external_message_id,
            "external_thread_id": message.external_thread_id,
            "sent_at": message.sent_at,
            "created_at": message.created_at,
        } for message in item.messages.all()]
    return data


def _apply(item, request, workspace):
    data = request.data
    for field in ("first_name", "last_name", "email", "phone", "company_name", "pet_notes", "summary", "notes", "source_label"):
        if field in data:
            setattr(item, field, str(data.get(field) or "").strip())
    if "email" in data:
        item.email = item.email.lower()
    if "stage" in data:
        value = str(data.get("stage") or "").upper()
        if value in LEAD_STAGES:
            item.stage = value
    if "lead_type" in data:
        value = str(data.get("lead_type") or "").upper()
        if value in LEAD_TYPES:
            item.lead_type = value
    if "source" in data:
        value = str(data.get("source") or "").upper()
        if value in LEAD_SOURCES:
            item.source = value
            if not item.source_label:
                item.source_label = PMLead.Source(value).label
    if "property" in data or "property_id" in data:
        property_id = data.get("property") or data.get("property_id")
        item.property = PMProperty.objects.filter(workspace=workspace, pk=property_id).first() if property_id else None
    for field in ("requested_start", "requested_end"):
        if field in data:
            setattr(item, field, parse_date(str(data.get(field) or "")) if data.get(field) else None)
    for field in ("adults", "children", "pets"):
        if field in data:
            try:
                setattr(item, field, max(0, int(data.get(field) or 0)))
            except (TypeError, ValueError):
                pass
    if "furnished_requested" in data:
        item.furnished_requested = bool(data.get("furnished_requested"))
    if "budget_amount" in data:
        item.budget_amount = _money(data.get("budget_amount"))
    return item


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def leads(request):
    workspace = requested_workspace(request)
    if request.method == "GET":
        qs = PMLead.objects.filter(workspace=workspace).select_related("property", "assigned_to").prefetch_related("messages")
        stage = str(request.query_params.get("stage") or "").upper()
        lead_type = str(request.query_params.get("lead_type") or "").upper()
        source = str(request.query_params.get("source") or "").upper()
        property_id = request.query_params.get("property")
        search = str(request.query_params.get("search") or "").strip()
        if stage:
            qs = qs.filter(stage=stage)
        if lead_type:
            qs = qs.filter(lead_type=lead_type)
        if source:
            qs = qs.filter(source=source)
        if property_id:
            qs = qs.filter(property_id=property_id)
        if search:
            qs = qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search) | Q(phone__icontains=search) | Q(company_name__icontains=search) | Q(source_subject__icontains=search) | Q(property__name__icontains=search))
        return Response({
            "leads": [_lead_data(item) for item in qs],
            "choices": {
                "stages": [{"value": value, "label": label} for value, label in PMLead.Stage.choices],
                "lead_types": [{"value": value, "label": label} for value, label in PMLead.LeadType.choices],
                "sources": [{"value": value, "label": label} for value, label in PMLead.Source.choices],
            },
        })
    item = PMLead(workspace=workspace, source=PMLead.Source.MANUAL, created_by=request.user)
    _apply(item, request, workspace)
    if not item.first_name and not item.last_name and not item.company_name and not item.email:
        return Response({"detail": "Add a lead name, company, or email."}, status=status.HTTP_400_BAD_REQUEST)
    item.save()
    return Response(_lead_data(item, include_messages=True), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def lead_detail(request, lead_id):
    workspace = requested_workspace(request)
    item = PMLead.objects.filter(workspace=workspace, pk=lead_id).select_related("property", "assigned_to").prefetch_related("messages").first()
    if not item:
        return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response(_lead_data(item, include_messages=True))
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    _apply(item, request, workspace)
    item.save()
    return Response(_lead_data(item, include_messages=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lead_note(request, lead_id):
    workspace = requested_workspace(request)
    item = PMLead.objects.filter(workspace=workspace, pk=lead_id).first()
    if not item:
        return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
    body = str(request.data.get("body") or "").strip()
    if not body:
        return Response({"detail": "Enter a note."}, status=status.HTTP_400_BAD_REQUEST)
    PMLeadMessage.objects.create(lead=item, direction=PMLeadMessage.Direction.INTERNAL, channel=PMLeadMessage.Channel.APP, sender_name=request.user.get_full_name() or request.user.email, sender_email=request.user.email, body=body, sent_by=request.user, sent_at=timezone.now())
    return Response(_lead_data(item, include_messages=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lead_reply_email(request, lead_id):
    workspace = requested_workspace(request)
    item = PMLead.objects.filter(workspace=workspace, pk=lead_id).first()
    if not item:
        return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
    to_email = str(request.data.get("to_email") or item.email or "").strip().lower()
    body = str(request.data.get("body") or "").strip()
    if not to_email or not body:
        return Response({"detail": "Recipient email and reply are required."}, status=status.HTTP_400_BAD_REQUEST)
    connection_id = str(request.data.get("connection_id") or item.mailbox_connection_id or "")
    connection = find_connection(request.user, connection_id) if connection_id else None
    if not connection or connection.get("provider") != "MICROSOFT":
        return Response({"detail": "Connect or select the Microsoft/Outlook mailbox that should send this reply."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        token, _ = connection_access_token(request.user, connection)
        subject_base = item.source_subject or f"Rental inquiry for {item.property.name if item.property else workspace.name}"
        subject = subject_base if f"SW-LEAD-{item.id}" in subject_base else f"[SW-LEAD-{item.id}] {subject_base}"
        send_microsoft_mail(token, to_email=to_email, subject=subject, body=body)
    except Exception as exc:
        return Response({"detail": f"Email could not be sent: {str(exc)[:300]}"}, status=status.HTTP_502_BAD_GATEWAY)
    PMLeadMessage.objects.create(lead=item, direction=PMLeadMessage.Direction.OUTBOUND, channel=PMLeadMessage.Channel.EMAIL, sender_name=request.user.get_full_name() or connection.get("display_name") or "Property Management", sender_email=connection.get("email") or request.user.email, recipient_email=to_email, subject=subject, body=body, mailbox_connection_id=connection.get("id") or "", sent_by=request.user, sent_at=timezone.now())
    if item.stage == PMLead.Stage.NEW:
        item.stage = PMLead.Stage.CONTACTED
    item.mailbox_connection_id = connection.get("id") or item.mailbox_connection_id
    item.save(update_fields=["stage", "mailbox_connection_id", "updated_at"])
    return Response(_lead_data(item, include_messages=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def lead_convert_to_tenant(request, lead_id):
    workspace = requested_workspace(request)
    item = PMLead.objects.filter(workspace=workspace, pk=lead_id).select_related("property").first()
    if not item:
        return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
    if item.stage != PMLead.Stage.WON:
        return Response({"detail": "Mark the lead Won before converting it to a tenant."}, status=status.HTTP_400_BAD_REQUEST)
    if not item.email:
        return Response({"detail": "Add the lead email before converting to a tenant."}, status=status.HTTP_400_BAD_REQUEST)
    existing = PMTenant.objects.filter(workspace=workspace, email__iexact=item.email).first()
    if existing:
        return Response({"tenant_id": existing.id, "detail": "This email is already a tenant in the portfolio."})
    tenant = PMTenant.objects.create(
        workspace=workspace,
        first_name=item.first_name or item.company_name or "Tenant",
        last_name=item.last_name,
        email=item.email.lower(),
        phone=item.phone,
        property_name=item.property.name if item.property else "",
        move_in_date=item.requested_start,
        notes=(item.notes + "\n\nLead source: " + (item.source_label or item.get_source_display())).strip(),
        created_by=request.user,
    )
    return Response({"tenant_id": tenant.id, "detail": "Lead converted to a tenant draft. Complete occupancy and lease details from the Tenant Center."}, status=status.HTTP_201_CREATED)
