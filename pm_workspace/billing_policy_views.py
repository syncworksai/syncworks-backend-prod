from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .advanced_billing_views import _normalize_rules, _workspace
from .billing_views import _active_lease, _profile_packet
from .models import PMDocumentPacket, PMTenant

TEMPLATE_PACKET_TYPE = "BILLING_POLICY_TEMPLATE"
AUDIT_PACKET_TYPE = "RENT_CHANGE_AUDIT"
TEMPLATE_DEFAULTS = {
    "late_fee_rules": [],
    "payment_arrangement_frequency": "BIWEEKLY",
    "pause_late_fees_during_arrangement": True,
    "collection_monthly_late_fee_cap": "0.00",
    "stop_late_fees_after_eviction": False,
    "payer_split_enabled": False,
    "installment_schedule_enabled": False,
    "installment_frequency": "BIWEEKLY",
    "installment_grace_days": 0,
    "installment_late_fee_amount": "50.00",
}
TEMPLATE_KEYS = tuple(TEMPLATE_DEFAULTS.keys())


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def _tenant(workspace, tenant_id):
    return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()


def _company_packet(workspace, create=False):
    packet = PMDocumentPacket.objects.filter(workspace=workspace, tenant__isnull=True, packet_type=TEMPLATE_PACKET_TYPE).order_by("-updated_at", "-id").first()
    if not packet and create:
        packet = PMDocumentPacket.objects.create(
            workspace=workspace,
            packet_type=TEMPLATE_PACKET_TYPE,
            template_name="Company billing policy",
            template_version="1",
            field_data={},
        )
    return packet


def _template_data(packet):
    data = dict(TEMPLATE_DEFAULTS)
    if packet and isinstance(packet.field_data, dict):
        for key in TEMPLATE_KEYS:
            if key in packet.field_data:
                data[key] = packet.field_data[key]
    data["late_fee_rules"] = _normalize_rules(data.get("late_fee_rules", []))
    return data


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def company_billing_template(request):
    workspace = _workspace(request)
    packet = _company_packet(workspace, create=request.method == "PATCH")
    if request.method == "GET":
        return Response({"template": _template_data(packet), "exists": bool(packet), "updated_at": packet.updated_at if packet else None})

    incoming = request.data or {}
    data = dict(packet.field_data or {})
    for key in TEMPLATE_KEYS:
        if key in incoming and key != "late_fee_rules":
            data[key] = incoming[key]
    if "late_fee_rules" in incoming:
        data["late_fee_rules"] = _normalize_rules(incoming.get("late_fee_rules"))
    packet.field_data = {key: data[key] for key in TEMPLATE_KEYS if key in data}
    packet.template_version = str(int(packet.template_version or "0") + 1)
    packet.save(update_fields=["field_data", "template_version", "updated_at"])
    return Response({"detail": "Company billing template saved.", "template": _template_data(packet), "updated_at": packet.updated_at})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_company_billing_template(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    packet = _company_packet(workspace)
    if not packet:
        return Response({"detail": "No company billing template has been saved yet."}, status=status.HTTP_400_BAD_REQUEST)
    profile_packet = _profile_packet(tenant, create=True)
    current = dict(profile_packet.field_data or {})
    template = _template_data(packet)
    for key in TEMPLATE_KEYS:
        current[key] = template[key]
    profile_packet.field_data = current
    profile_packet.lease = _active_lease(tenant)
    profile_packet.save(update_fields=["field_data", "lease", "updated_at"])
    return Response({"detail": "Company billing template applied to this tenant without changing tenant-specific balances, deposits, or case status.", "profile": current})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def rent_allocation(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    lease = _active_lease(tenant)
    if not lease:
        return Response({"detail": "An active lease is required before rent allocation can be changed."}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "GET":
        audits = PMDocumentPacket.objects.filter(workspace=workspace, tenant=tenant, packet_type=AUDIT_PACKET_TYPE).order_by("-created_at")[:10]
        return Response({
            "allocation": {
                "contract_rent": str(lease.monthly_rent),
                "tenant_portion": str(lease.tenant_portion or Decimal("0.00")),
                "housing_portion": str(lease.assistance_portion or Decimal("0.00")),
                "section8": lease.section8,
                "lease_id": lease.id,
            },
            "history": [dict(packet.field_data or {}, id=packet.id, created_at=packet.created_at) for packet in audits],
        })

    incoming = request.data or {}
    contract = _money(incoming.get("contract_rent", lease.monthly_rent))
    tenant_portion = _money(incoming.get("tenant_portion", lease.tenant_portion or "0.00"))
    housing_portion = _money(incoming.get("housing_portion", lease.assistance_portion or "0.00"))
    if contract < 0 or tenant_portion < 0 or housing_portion < 0:
        return Response({"detail": "Rent amounts cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
    if lease.section8 and tenant_portion + housing_portion != contract:
        return Response({"detail": "Tenant portion plus Housing portion must equal contract rent."}, status=status.HTTP_400_BAD_REQUEST)
    if not lease.section8:
        tenant_portion = contract
        housing_portion = Decimal("0.00")

    reason_type = str(incoming.get("reason_type") or "").upper()
    if reason_type not in {"CORRECTION", "LEASE_CHANGE"}:
        return Response({"reason_type": "Choose Data correction or Lease / rent change."}, status=status.HTTP_400_BAD_REQUEST)
    reason = str(incoming.get("reason") or "").strip()
    if not reason:
        return Response({"reason": "Add a short reason for the change."}, status=status.HTTP_400_BAD_REQUEST)

    old = {
        "contract_rent": str(lease.monthly_rent),
        "tenant_portion": str(lease.tenant_portion or Decimal("0.00")),
        "housing_portion": str(lease.assistance_portion or Decimal("0.00")),
    }
    new = {"contract_rent": str(contract), "tenant_portion": str(tenant_portion), "housing_portion": str(housing_portion)}
    if old == new:
        return Response({"detail": "No rent allocation changes were detected.", "allocation": new})

    supporting_document_id = incoming.get("supporting_document_id") or None
    document_pending = bool(incoming.get("document_pending", False))
    document_required = reason_type == "LEASE_CHANGE"
    if document_required and not supporting_document_id and not document_pending:
        return Response({"detail": "A lease/rent change requires a supporting lease document or Mark paperwork pending."}, status=status.HTTP_400_BAD_REQUEST)

    lease.monthly_rent = contract
    lease.tenant_portion = tenant_portion
    lease.assistance_portion = housing_portion
    lease.save(update_fields=["monthly_rent", "tenant_portion", "assistance_portion", "updated_at"])
    tenant.monthly_rent = contract
    tenant.save(update_fields=["monthly_rent", "updated_at"])

    audit = PMDocumentPacket.objects.create(
        workspace=workspace,
        tenant=tenant,
        lease=lease,
        packet_type=AUDIT_PACKET_TYPE,
        template_name="Rent allocation change record",
        template_version="1",
        field_data={
            "changed_at": timezone.now().isoformat(),
            "changed_by_user_id": request.user.id,
            "changed_by_email": getattr(request.user, "email", "") or "",
            "reason_type": reason_type,
            "reason": reason,
            "old": old,
            "new": new,
            "supporting_document_id": supporting_document_id,
            "document_required": document_required,
            "document_pending": document_pending,
        },
    )
    return Response({
        "detail": "Rent allocation updated and change history recorded.",
        "allocation": new,
        "audit_id": audit.id,
        "documentation_required": document_required,
        "document_pending": document_pending,
    })
