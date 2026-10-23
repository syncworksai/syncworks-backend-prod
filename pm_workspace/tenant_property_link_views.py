"""Explicit, audited owner-confirmed linking of existing tenant to existing property.

Never creates a tenant, changes a lease, payment, rent, or deposit.
"""
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PMProperty, PMTenant, PMLease
from .lifecycle_models import PMOccupancy
from .views import _requested_workspace

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def link_existing_tenant(request,property_id,tenant_id):
    ws=_requested_workspace(request)
    prop=PMProperty.objects.filter(workspace=ws,pk=property_id).first()
    tenant=PMTenant.objects.select_for_update().filter(workspace=ws,pk=tenant_id).first()
    if not prop or not tenant:return Response({"detail":"Property or resident record not found."},status=404)
    if request.data.get("confirmed") is not True:
        return Response({"detail":"Confirm this is the correct existing property and resident before linking."},status=400)
    existing=tenant.property_id
    if existing and existing!=prop.id:
        return Response({"detail":"Tenant is linked to another property. Review and correct the active tenancy before reassignment."},status=409)
    conflicting_lease=PMLease.objects.filter(workspace=ws,tenant=tenant,unit__isnull=False).exclude(
        unit__property=prop).exists()
    conflicting_occupancy=PMOccupancy.objects.filter(workspace=ws,tenant=tenant,status__in=("ACTIVE","PENDING","NOTICE_GIVEN")).exclude(property=prop).exists()
    if conflicting_lease or conflicting_occupancy:
        return Response({"detail":"An existing lease or active occupancy points to another property. Resolve that conflict first."},status=409)
    if tenant.property_id==prop.id:
        return Response({"linked":True,"tenant_id":tenant.id,"property_id":prop.id,"unchanged":True})
    original=tenant.property_name
    tenant.property=prop
    tenant.property_name=prop.name
    note=f"[PM property link] Owner confirmed existing resident {tenant.id} linked to property {prop.id}; previous property label: {original!r}."
    tenant.notes=(tenant.notes+"\n"+note).strip()
    tenant.save(update_fields=["property","property_name","notes","updated_at"])
    return Response({"linked":True,"tenant_id":tenant.id,"property_id":prop.id,
                     "unchanged":False,"detail":"Existing records linked. No lease terms, payments or balances changed."})
