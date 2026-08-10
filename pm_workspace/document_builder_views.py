from __future__ import annotations

from copy import deepcopy
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .advanced_billing_views import _advanced_profile
from .document_models import PMPropertyDocument
from .lifecycle_models import PMOccupancy, PMTenantCase
from .models import PMDocumentPacket, PMLease, PMProperty, PMTenant, PMUnit, PMWorkspace
from .owner_models import PMPropertyOwner


DOCUMENT_TEMPLATES = [
    {
        "id": "residential_lease",
        "name": "Residential Lease",
        "category": "LEASE",
        "requires_tenant": True,
        "description": "Reusable residential lease shell populated from saved property, tenant, lease, billing, owner, and housing-assistance data.",
    },
    {
        "id": "move_in_inspection",
        "name": "Move-In Inspection & Condition Report",
        "category": "MOVE_IN_INSPECTION",
        "requires_tenant": True,
        "description": "Room-by-room move-in condition checklist with keys, meters, photos, signatures, and notes.",
    },
    {
        "id": "security_deposit_receipt",
        "name": "Security Deposit Receipt / Agreement",
        "category": "SECURITY_DEPOSIT",
        "requires_tenant": True,
        "description": "Deposit amount, receipt date, held/applied amounts, and acknowledgement.",
    },
    {
        "id": "payment_arrangement",
        "name": "Payment Arrangement Agreement",
        "category": "PAYMENT_ARRANGEMENT",
        "requires_tenant": True,
        "description": "Current balance, installment cadence, dates, late-fee treatment, and acknowledgement.",
    },
    {
        "id": "move_out_inspection",
        "name": "Move-Out Inspection & Deposit Disposition",
        "category": "MOVE_OUT_INSPECTION",
        "requires_tenant": True,
        "description": "Move-out condition, damages, keys, deposit disposition, forwarding address, and make-ready notes.",
    },
    {
        "id": "nonpayment_notice",
        "name": "Nonpayment / Lease Notice",
        "category": "NOTICE",
        "requires_tenant": True,
        "description": "Editable notice shell using saved tenant, property, lease, balance, and delivery information. Final language must be company-approved.",
    },
    {
        "id": "collections_packet",
        "name": "Collections / Legal Account Summary",
        "category": "NOTICE",
        "requires_tenant": True,
        "description": "Former-tenant account summary with occupancy, case, balance, move-out, agency, and supporting-document information.",
    },
    {
        "id": "owner_make_ready_scope",
        "name": "Owner Make-Ready Scope & Approval",
        "category": "OTHER",
        "requires_tenant": False,
        "description": "Property make-ready scope, owner approval limit, work summary, target date, and approval acknowledgement.",
    },
]


def _workspace(request):
    workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
    if not workspace_id and isinstance(request.data, dict):
        workspace_id = request.data.get("workspace_id")
    qs = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    workspace = qs.filter(pk=workspace_id).first() if workspace_id else qs.order_by("id").first()
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


def _property(workspace, property_id):
    return PMProperty.objects.filter(workspace=workspace, pk=property_id).first()


def _tenant_ids_for_property(workspace, property_obj):
    ids = set(PMOccupancy.objects.filter(workspace=workspace, property=property_obj).values_list("tenant_id", flat=True))
    legacy = PMTenant.objects.filter(workspace=workspace).filter(Q(property_name__iexact=property_obj.name) | Q(property_name__iexact=property_obj.address)).values_list("id", flat=True)
    ids.update(legacy)
    return ids


def _owner(workspace, property_obj):
    return PMPropertyOwner.objects.filter(workspace=workspace, properties=property_obj).order_by("id").first()


def _lease(tenant):
    return PMLease.objects.filter(workspace=tenant.workspace, tenant=tenant).select_related("unit").order_by("-start_date", "-id").first()


def _occupancy(workspace, property_obj, tenant):
    return PMOccupancy.objects.filter(workspace=workspace, property=property_obj, tenant=tenant).select_related("unit", "lease").order_by("-move_in_date", "-id").first()


def _case(workspace, property_obj, tenant):
    return PMTenantCase.objects.filter(workspace=workspace, property=property_obj, tenant=tenant).order_by("-opened_date", "-id").first()


def _money(value):
    return str(value if value not in (None, "") else "0.00")


def _iso(value):
    return value.isoformat() if value else ""


def _late_fee_summary(profile):
    rules = profile.get("late_fee_rules") or []
    parts = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        mode = str(rule.get("mode") or "").upper()
        trigger = rule.get("trigger")
        amount = _money(rule.get("amount"))
        if mode == "FIXED_DAY":
            parts.append(f"${amount} on day {trigger} when unpaid")
        elif mode == "DAYS_LATE":
            parts.append(f"${amount} after {trigger} day(s) late")
        elif mode == "DAILY":
            cap = _money(rule.get("monthly_cap"))
            parts.append(f"${amount} per day after {trigger} day(s) late" + (f", monthly cap ${cap}" if cap != "0.00" else ""))
    return "; ".join(parts)


def _base_fields(workspace, property_obj, tenant=None):
    owner = _owner(workspace, property_obj)
    lease = _lease(tenant) if tenant else None
    occupancy = _occupancy(workspace, property_obj, tenant) if tenant else None
    case = _case(workspace, property_obj, tenant) if tenant else None
    unit = occupancy.unit if occupancy and occupancy.unit_id else lease.unit if lease and lease.unit_id else None
    profile = _advanced_profile(tenant) if tenant else {}
    return {
        "generated_on": timezone.localdate().isoformat(),
        "property_id": property_obj.id,
        "property_name": property_obj.name,
        "property_type": property_obj.property_type,
        "property_address": property_obj.address,
        "property_city": property_obj.city,
        "property_state": property_obj.state,
        "property_zip": property_obj.zip,
        "property_notes": property_obj.notes,
        "unit_id": unit.id if unit else None,
        "unit_label": unit.label if unit else (tenant.unit_label if tenant else ""),
        "owner_name": owner.name if owner else workspace.name,
        "owner_email": owner.email if owner else "",
        "owner_phone": owner.phone if owner else "",
        "owner_mailing_address": owner.mailing_address if owner else "",
        "manager_name": workspace.manager_name or workspace.name,
        "manager_email": workspace.office_email,
        "manager_phone": workspace.phone,
        "manager_address": workspace.office_address,
        "tenant_id": tenant.id if tenant else None,
        "tenant_name": f"{tenant.first_name} {tenant.last_name}".strip() if tenant else "",
        "tenant_email": tenant.email if tenant else "",
        "tenant_phone": tenant.phone if tenant else "",
        "tenant_notes": tenant.notes if tenant else "",
        "lease_id": lease.id if lease else None,
        "lease_term": lease.term if lease else "",
        "lease_start": _iso(lease.start_date if lease else tenant.lease_start if tenant else None),
        "lease_end": _iso(lease.end_date if lease and lease.end_date else tenant.lease_end if tenant else None),
        "monthly_rent": _money(lease.monthly_rent if lease else tenant.monthly_rent if tenant else None),
        "security_deposit": _money(lease.security_deposit if lease else profile.get("deposit_required")),
        "section8": bool(lease.section8) if lease else False,
        "housing_authority": lease.housing_authority if lease else "",
        "tenant_portion": _money(lease.tenant_portion if lease else None),
        "assistance_portion": _money(lease.assistance_portion if lease else None),
        "occupancy_id": occupancy.id if occupancy else None,
        "occupancy_status": occupancy.status if occupancy else "",
        "move_in_date": _iso(occupancy.move_in_date if occupancy else tenant.move_in_date if tenant else None),
        "notice_date": _iso(occupancy.notice_date if occupancy else None),
        "move_out_date": _iso(occupancy.move_out_date if occupancy else None),
        "move_out_reason": occupancy.move_out_reason if occupancy else "",
        "forwarding_address": occupancy.forwarding_address if occupancy else "",
        "case_id": case.id if case else None,
        "case_type": case.case_type if case else "",
        "case_status": case.status if case else "",
        "case_reference": case.reference if case else "",
        "case_agency_name": case.agency_name if case else "",
        "case_agency_email": case.agency_email if case else "",
        "case_current_balance": _money(case.current_balance if case else None),
        "rent_due_day": int(profile.get("rent_due_day") or 1),
        "late_fee_summary": _late_fee_summary(profile),
        "payment_arrangement_enabled": bool(profile.get("payment_arrangement_enabled")),
        "payment_arrangement_frequency": profile.get("payment_arrangement_frequency") or "",
        "payment_arrangement_amount": _money(profile.get("payment_arrangement_amount")),
        "payment_arrangement_start": profile.get("payment_arrangement_start") or "",
        "payment_arrangement_end": profile.get("payment_arrangement_end") or "",
        "deposit_required": _money(profile.get("deposit_required")),
        "deposit_received": _money(profile.get("deposit_received")),
        "deposit_held": _money(profile.get("deposit_held")),
        "deposit_applied": _money(profile.get("deposit_applied")),
        "deposit_notes": profile.get("deposit_notes") or "",
        "collection_status": profile.get("collection_status") or "NONE",
        "collection_start_date": profile.get("collection_start_date") or "",
        "collections_recipient_name": profile.get("collections_recipient_name") or "",
        "collections_recipient_email": profile.get("collections_recipient_email") or "",
        "collections_notes": profile.get("collections_notes") or "",
    }


def _template_fields(template_id, fields):
    base = deepcopy(fields)
    if template_id == "residential_lease":
        base.update({
            "document_title": f"Residential Lease Agreement - {fields['property_name']}",
            "utilities_landlord": [],
            "utilities_tenant": [],
            "included_appliances": [],
            "authorized_occupants": [fields["tenant_name"]] if fields.get("tenant_name") else [],
            "pet_terms": "",
            "maintenance_terms": "Tenant will promptly report needed repairs and maintain the premises as required by the approved lease template.",
            "special_terms": "",
            "addenda": ["Housing assistance tenancy addendum"] if fields.get("section8") else [],
        })
    elif template_id == "move_in_inspection":
        base.update({"document_title": f"Move-In Inspection - {fields['property_name']}", "inspection_date": fields.get("move_in_date") or fields["generated_on"], "rooms": ["Exterior", "Entry", "Living Room", "Kitchen", "Bedroom(s)", "Bathroom(s)", "HVAC", "Plumbing", "Electrical", "Appliances"], "condition_notes": {}, "keys_received": "", "meter_readings": "", "photo_notes": ""})
    elif template_id == "security_deposit_receipt":
        base.update({"document_title": f"Security Deposit Receipt - {fields.get('tenant_name') or fields['property_name']}", "receipt_date": fields["generated_on"], "payment_method": "", "deposit_terms": fields.get("deposit_notes") or ""})
    elif template_id == "payment_arrangement":
        base.update({"document_title": f"Payment Arrangement - {fields.get('tenant_name')}", "current_balance": fields.get("case_current_balance") or "0.00", "first_payment_date": fields.get("payment_arrangement_start") or "", "arrangement_notes": "", "default_terms": ""})
    elif template_id == "move_out_inspection":
        base.update({"document_title": f"Move-Out Inspection - {fields['property_name']}", "inspection_date": fields.get("move_out_date") or fields["generated_on"], "rooms": ["Exterior", "Entry", "Living Room", "Kitchen", "Bedroom(s)", "Bathroom(s)", "HVAC", "Plumbing", "Electrical", "Appliances"], "condition_notes": {}, "keys_returned": "", "damage_charges": [], "make_ready_notes": "", "deposit_disposition_notes": fields.get("deposit_notes") or ""})
    elif template_id == "nonpayment_notice":
        base.update({"document_title": f"Notice - {fields.get('tenant_name') or fields['property_name']}", "notice_date": fields["generated_on"], "amount_due": fields.get("case_current_balance") or "0.00", "notice_body": "Use company-approved notice language here before delivery.", "delivery_method": "", "delivery_date": ""})
    elif template_id == "collections_packet":
        base.update({"document_title": f"Collections Account Summary - {fields.get('tenant_name')}", "account_summary": "", "repair_charges_summary": "", "supporting_documents": [], "adjustment_notes": fields.get("collections_notes") or ""})
    elif template_id == "owner_make_ready_scope":
        base.update({"document_title": f"Make-Ready Scope & Approval - {fields['property_name']}", "scope_items": [], "estimated_cost": "0.00", "approval_limit": "0.00", "target_completion_date": "", "vendor_or_team": "", "owner_approval_notes": ""})
    return base


def _template(template_id):
    return next((item for item in DOCUMENT_TEMPLATES if item["id"] == template_id), None)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_builder_bootstrap(request, property_id):
    workspace = _workspace(request)
    property_obj = _property(workspace, property_id)
    if not property_obj:
        return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
    tenant_ids = _tenant_ids_for_property(workspace, property_obj)
    tenants = PMTenant.objects.filter(workspace=workspace, id__in=tenant_ids).order_by("status", "last_name", "first_name")
    packets = PMDocumentPacket.objects.filter(workspace=workspace, packet_type="DOCUMENT_BUILDER", field_data__generated_from__property_id=property_obj.id).order_by("-updated_at", "-id")
    return Response({
        "property": {"id": property_obj.id, "name": property_obj.name, "address": property_obj.address, "city": property_obj.city, "state": property_obj.state, "zip": property_obj.zip},
        "templates": DOCUMENT_TEMPLATES,
        "tenants": [{"id": tenant.id, "name": f"{tenant.first_name} {tenant.last_name}".strip(), "email": tenant.email, "status": tenant.status, "property_name": tenant.property_name, "unit_label": tenant.unit_label} for tenant in tenants],
        "drafts": [{"id": packet.id, "template_name": packet.template_name, "status": packet.status, "tenant_id": packet.tenant_id, "field_data": packet.field_data, "updated_at": packet.updated_at} for packet in packets],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_builder_prefill(request, property_id, template_id):
    workspace = _workspace(request)
    property_obj = _property(workspace, property_id)
    template = _template(template_id)
    if not property_obj or not template:
        return Response({"detail": "Property or document template not found."}, status=status.HTTP_404_NOT_FOUND)
    tenant_id = request.query_params.get("tenant_id")
    tenant = None
    if tenant_id:
        tenant = PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()
        if not tenant or tenant.id not in _tenant_ids_for_property(workspace, property_obj):
            return Response({"detail": "Choose a tenant connected to this property's history."}, status=status.HTTP_400_BAD_REQUEST)
    if template["requires_tenant"] and not tenant:
        return Response({"detail": "Choose a tenant for this document."}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"template": template, "fields": _template_fields(template_id, _base_fields(workspace, property_obj, tenant))})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def document_builder_save(request, property_id):
    workspace = _workspace(request)
    property_obj = _property(workspace, property_id)
    template_id = str(request.data.get("template_id") or "")
    template = _template(template_id)
    if not property_obj or not template:
        return Response({"detail": "Choose a valid property and document template."}, status=status.HTTP_400_BAD_REQUEST)
    tenant_id = request.data.get("tenant_id")
    tenant = PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first() if tenant_id else None
    if tenant and tenant.id not in _tenant_ids_for_property(workspace, property_obj):
        return Response({"detail": "The selected tenant is not connected to this property history."}, status=status.HTTP_400_BAD_REQUEST)
    if template["requires_tenant"] and not tenant:
        return Response({"detail": "Choose a tenant for this document."}, status=status.HTTP_400_BAD_REQUEST)
    incoming = request.data.get("fields") or {}
    if not isinstance(incoming, dict):
        return Response({"detail": "Document fields must be an object."}, status=status.HTTP_400_BAD_REQUEST)
    fields = _template_fields(template_id, _base_fields(workspace, property_obj, tenant))
    fields.update(deepcopy(incoming))
    fields["template_id"] = template_id
    fields["generated_from"] = {"source": "SYNCWORKS_DOCUMENT_BUILDER", "property_id": property_obj.id, "tenant_id": tenant.id if tenant else None, "generated_at": timezone.now().isoformat()}
    lease = _lease(tenant) if tenant else None
    packet_id = request.data.get("packet_id")
    packet = PMDocumentPacket.objects.filter(workspace=workspace, pk=packet_id, packet_type="DOCUMENT_BUILDER").first() if packet_id else None
    if not packet:
        packet = PMDocumentPacket(workspace=workspace, packet_type="DOCUMENT_BUILDER")
    packet.tenant = tenant
    packet.lease = lease
    packet.state_code = property_obj.state
    packet.housing_authority = fields.get("housing_authority") or ""
    packet.template_name = template["name"]
    packet.template_version = "1.0"
    packet.field_data = fields
    packet.status = PMDocumentPacket.Status.DRAFT
    packet.save()

    document_id = fields.get("property_document_id")
    document = PMPropertyDocument.objects.filter(workspace=workspace, property=property_obj, pk=document_id).first() if document_id else None
    if not document:
        document = PMPropertyDocument(workspace=workspace, property=property_obj, created_by=request.user)
    document.tenant = tenant
    document.lease = lease
    document.category = template["category"]
    document.title = fields.get("document_title") or template["name"]
    document.source_name = "Generated in SyncWorks"
    document.state_code = property_obj.state
    document.housing_authority = fields.get("housing_authority") or ""
    document.status = PMPropertyDocument.Status.DRAFT
    document.effective_date = lease.start_date if lease and template_id == "residential_lease" else None
    document.notes = "Structured document generated inside SyncWorks. Use Preview / Print to export the current version as PDF."
    document.extracted_terms = {"packet_id": packet.id, "template_id": template_id, "fields": fields}
    document.save()
    fields["property_document_id"] = document.id
    packet.field_data = fields
    packet.save(update_fields=["field_data", "updated_at"])
    return Response({"detail": "Document draft saved to the property and tenant records.", "packet": {"id": packet.id, "status": packet.status, "template_name": packet.template_name, "field_data": packet.field_data}, "property_document_id": document.id}, status=status.HTTP_201_CREATED if not packet_id else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def document_builder_finalize(request, packet_id):
    workspace = _workspace(request)
    packet = PMDocumentPacket.objects.filter(workspace=workspace, pk=packet_id, packet_type="DOCUMENT_BUILDER").first()
    if not packet:
        return Response({"detail": "Document draft not found."}, status=status.HTTP_404_NOT_FOUND)
    fields = dict(packet.field_data or {})
    required = ["document_title", "property_name", "property_address"]
    if packet.tenant_id:
        required.append("tenant_name")
    missing = [key for key in required if not str(fields.get(key) or "").strip()]
    if missing:
        return Response({"detail": f"Complete required fields: {', '.join(missing)}."}, status=status.HTTP_400_BAD_REQUEST)
    fields["document_status"] = "READY_FOR_SIGNATURE" if request.data.get("ready_for_signature", True) else "FINAL_REVIEW"
    fields["finalized_at"] = timezone.now().isoformat()
    packet.field_data = fields
    packet.status = PMDocumentPacket.Status.DRAFT
    packet.save(update_fields=["field_data", "status", "updated_at"])
    document_id = fields.get("property_document_id")
    if document_id:
        PMPropertyDocument.objects.filter(workspace=workspace, pk=document_id).update(status=PMPropertyDocument.Status.PENDING_SIGNATURE if request.data.get("ready_for_signature", True) else PMPropertyDocument.Status.DRAFT, extracted_terms={"packet_id": packet.id, "template_id": fields.get("template_id"), "fields": fields})
    return Response({"detail": "Document is ready for PDF review." if not request.data.get("ready_for_signature", True) else "Document is ready for PDF review and signatures.", "packet_id": packet.id, "status": packet.status, "field_data": fields})
