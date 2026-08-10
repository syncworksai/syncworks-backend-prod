from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PMDocumentPacket, PMLease, PMProperty, PMTenant, PMUnit, PMWorkspace
from .owner_models import PMPropertyOwner


LEASE_TEMPLATES = [
    {
        "id": "standard_residential",
        "name": "Standard Residential Lease",
        "description": "General residential lease shell with property, rent, deposit, utilities, occupancy, maintenance, notices, and signature sections.",
        "recommended_for": ["HOME", "TOWNHOME", "CONDO", "MULTIFAMILY", "APARTMENT"],
        "sections": [
            "Parties and Premises",
            "Lease Term",
            "Rent and Payment Schedule",
            "Security Deposit",
            "Late Fees and Payment Arrangements",
            "Utilities and Services",
            "Occupancy and Guests",
            "Maintenance and Repairs",
            "Rules and Addenda",
            "Notices",
            "Signatures",
        ],
    },
    {
        "id": "month_to_month",
        "name": "Month-to-Month Rental Agreement",
        "description": "Month-to-month agreement shell with recurring rent, notice periods, deposit, utilities, and signatures.",
        "recommended_for": ["HOME", "TOWNHOME", "CONDO", "MULTIFAMILY", "APARTMENT"],
        "sections": [
            "Parties and Premises",
            "Month-to-Month Term",
            "Rent and Due Date",
            "Security Deposit",
            "Late Fees",
            "Utilities and Services",
            "Occupancy",
            "Maintenance",
            "Termination Notice",
            "Signatures",
        ],
    },
    {
        "id": "section8_residential",
        "name": "Housing Assistance Residential Lease",
        "description": "Residential lease shell with housing-authority, tenant-portion, assistance-portion, inspection, and required-addendum tracking.",
        "recommended_for": ["HOME", "TOWNHOME", "CONDO", "MULTIFAMILY", "APARTMENT"],
        "sections": [
            "Parties and Premises",
            "Lease Term",
            "Contract Rent",
            "Tenant and Assistance Portions",
            "Security Deposit",
            "Utilities and Appliances",
            "Housing Authority and Required Addenda",
            "Inspection and Compliance",
            "Maintenance and Repairs",
            "Notices",
            "Signatures",
        ],
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


def _tenant_property_match(property_obj):
    return Q(property_name__iexact=property_obj.name) | Q(property_name__iexact=property_obj.address)


def _money(value):
    return str(value or "0.00")


def _lease_fields(workspace, property_obj, tenant=None, lease=None, unit=None):
    owner = PMPropertyOwner.objects.filter(workspace=workspace, properties=property_obj).order_by("id").first()
    lease = lease or (tenant.leases.order_by("-start_date", "-id").first() if tenant else None)
    unit = unit or (lease.unit if lease and lease.unit_id else None)
    monthly_rent = lease.monthly_rent if lease else tenant.monthly_rent if tenant else None
    security_deposit = lease.security_deposit if lease else None
    section8 = bool(lease.section8) if lease else False
    housing_authority = lease.housing_authority if lease else ""
    return {
        "template_id": "section8_residential" if section8 else "standard_residential",
        "document_title": f"Residential Lease - {property_obj.name}",
        "landlord_name": owner.name if owner else workspace.name,
        "landlord_email": owner.email if owner and owner.email else workspace.office_email,
        "landlord_phone": owner.phone if owner and owner.phone else workspace.phone,
        "landlord_mailing_address": owner.mailing_address if owner else workspace.office_address,
        "property_name": property_obj.name,
        "property_address": property_obj.address,
        "property_city": property_obj.city,
        "property_state": property_obj.state,
        "property_zip": property_obj.zip,
        "unit_label": unit.label if unit else tenant.unit_label if tenant else "",
        "tenant_id": tenant.id if tenant else None,
        "tenant_name": f"{tenant.first_name} {tenant.last_name}".strip() if tenant else "",
        "tenant_email": tenant.email if tenant else "",
        "tenant_phone": tenant.phone if tenant else "",
        "lease_id": lease.id if lease else None,
        "lease_term": lease.term if lease else "TWELVE_MONTH",
        "lease_start": str(lease.start_date if lease else tenant.lease_start if tenant else ""),
        "lease_end": str(lease.end_date if lease and lease.end_date else tenant.lease_end if tenant and tenant.lease_end else ""),
        "converts_to_month_to_month": bool(lease.converts_to_month_to_month) if lease else True,
        "monthly_rent": _money(monthly_rent),
        "rent_due_day": 1,
        "security_deposit": _money(security_deposit),
        "section8": section8,
        "housing_authority": housing_authority,
        "tenant_portion": _money(lease.tenant_portion if lease else None),
        "assistance_portion": _money(lease.assistance_portion if lease else None),
        "late_fee_summary": "",
        "payment_arrangement_summary": "",
        "utilities_landlord": [],
        "utilities_tenant": [],
        "included_appliances": [],
        "occupants": [f"{tenant.first_name} {tenant.last_name}".strip()] if tenant else [],
        "pet_terms": "",
        "maintenance_terms": "Tenant must promptly report needed repairs and avoid causing damage beyond normal wear.",
        "special_terms": "",
        "addenda": ["Housing assistance tenancy addendum"] if section8 else [],
        "manager_name": workspace.manager_name,
        "manager_email": workspace.office_email,
        "manager_phone": workspace.phone,
        "signature_status": "DRAFT",
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lease_builder_bootstrap(request, property_id):
    workspace = _workspace(request)
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    if not property_obj:
        return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
    tenants = PMTenant.objects.filter(workspace=workspace).filter(_tenant_property_match(property_obj)).prefetch_related("leases").order_by("last_name", "first_name")
    units = PMUnit.objects.filter(workspace=workspace, property=property_obj).order_by("label")
    packets = PMDocumentPacket.objects.filter(workspace=workspace, tenant__in=tenants, packet_type="LEASE_BUILDER").select_related("tenant", "lease").order_by("-updated_at")
    return Response({
        "property": {
            "id": property_obj.id,
            "name": property_obj.name,
            "address": property_obj.address,
            "city": property_obj.city,
            "state": property_obj.state,
            "zip": property_obj.zip,
            "property_type": property_obj.property_type,
        },
        "templates": LEASE_TEMPLATES,
        "tenants": [
            {
                "id": tenant.id,
                "name": f"{tenant.first_name} {tenant.last_name}".strip(),
                "email": tenant.email,
                "phone": tenant.phone,
                "unit_label": tenant.unit_label,
                "lease_start": tenant.lease_start,
                "lease_end": tenant.lease_end,
                "monthly_rent": tenant.monthly_rent,
                "active_lease_id": tenant.leases.order_by("-start_date", "-id").values_list("id", flat=True).first(),
            }
            for tenant in tenants
        ],
        "units": [{"id": unit.id, "label": unit.label, "market_rent": unit.market_rent, "availability": unit.availability} for unit in units],
        "drafts": [
            {
                "id": packet.id,
                "tenant_id": packet.tenant_id,
                "tenant_name": f"{packet.tenant.first_name} {packet.tenant.last_name}".strip() if packet.tenant else "",
                "template_name": packet.template_name,
                "status": packet.status,
                "updated_at": packet.updated_at,
                "field_data": packet.field_data,
            }
            for packet in packets
        ],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def lease_builder_prefill(request, property_id, tenant_id):
    workspace = _workspace(request)
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    tenant = PMTenant.objects.filter(workspace=workspace, pk=tenant_id).filter(_tenant_property_match(property_obj)).first() if property_obj else None
    if not property_obj or not tenant:
        return Response({"detail": "Property or tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"fields": _lease_fields(workspace, property_obj, tenant=tenant), "templates": LEASE_TEMPLATES})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def lease_builder_save(request, property_id):
    workspace = _workspace(request)
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    tenant = PMTenant.objects.filter(workspace=workspace, pk=request.data.get("tenant_id")).first()
    if not property_obj or not tenant or not PMTenant.objects.filter(pk=tenant.pk).filter(_tenant_property_match(property_obj)).exists():
        return Response({"detail": "Choose a tenant connected to this property."}, status=status.HTTP_400_BAD_REQUEST)
    incoming = deepcopy(request.data.get("fields") or {})
    if not isinstance(incoming, dict):
        return Response({"detail": "Lease fields must be an object."}, status=status.HTTP_400_BAD_REQUEST)
    template_id = str(incoming.get("template_id") or request.data.get("template_id") or "standard_residential")
    template = next((item for item in LEASE_TEMPLATES if item["id"] == template_id), None)
    if not template:
        return Response({"detail": "Choose a valid lease template."}, status=status.HTTP_400_BAD_REQUEST)
    lease = PMLease.objects.filter(workspace=workspace, tenant=tenant).order_by("-start_date", "-id").first()
    defaults = _lease_fields(workspace, property_obj, tenant=tenant, lease=lease)
    defaults.update(incoming)
    defaults["template_id"] = template_id
    defaults["template_sections"] = template["sections"]
    defaults["generated_from"] = {
        "property_id": property_obj.id,
        "tenant_id": tenant.id,
        "lease_id": lease.id if lease else None,
        "source": "SYNCWORKS_INTERNAL_LEASE_BUILDER",
    }
    packet_id = request.data.get("packet_id")
    packet = PMDocumentPacket.objects.filter(workspace=workspace, pk=packet_id, packet_type="LEASE_BUILDER").first() if packet_id else None
    if not packet:
        packet = PMDocumentPacket(workspace=workspace, packet_type="LEASE_BUILDER")
    packet.tenant = tenant
    packet.lease = lease
    packet.state_code = property_obj.state
    packet.housing_authority = str(defaults.get("housing_authority") or "")
    packet.template_name = template["name"]
    packet.template_version = "1.0"
    packet.field_data = defaults
    packet.status = PMDocumentPacket.Status.DRAFT
    packet.save()
    return Response({
        "detail": "Lease draft saved.",
        "packet": {
            "id": packet.id,
            "status": packet.status,
            "template_name": packet.template_name,
            "tenant_id": packet.tenant_id,
            "lease_id": packet.lease_id,
            "field_data": packet.field_data,
            "updated_at": packet.updated_at,
        },
    }, status=status.HTTP_201_CREATED if not packet_id else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lease_builder_finalize(request, packet_id):
    workspace = _workspace(request)
    packet = PMDocumentPacket.objects.filter(workspace=workspace, pk=packet_id, packet_type="LEASE_BUILDER").select_related("tenant", "lease").first()
    if not packet:
        return Response({"detail": "Lease draft not found."}, status=status.HTTP_404_NOT_FOUND)
    fields = dict(packet.field_data or {})
    required = ["landlord_name", "tenant_name", "property_address", "lease_start", "monthly_rent"]
    missing = [field for field in required if not str(fields.get(field) or "").strip()]
    if missing:
        return Response({"detail": f"Complete required fields: {', '.join(missing)}."}, status=status.HTTP_400_BAD_REQUEST)
    fields["signature_status"] = "READY_FOR_SIGNATURE"
    packet.field_data = fields
    packet.status = PMDocumentPacket.Status.SENT if request.data.get("mark_sent") else PMDocumentPacket.Status.DRAFT
    packet.save(update_fields=["field_data", "status", "updated_at"])
    return Response({
        "detail": "Lease is ready for PDF review and signatures.",
        "packet_id": packet.id,
        "status": packet.status,
        "field_data": packet.field_data,
    })
