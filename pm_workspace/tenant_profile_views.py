from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .lifecycle_models import PMOccupancy
from .models import PMProperty, PMTenant, PMTenantInvitation, PMUnit
from .serializers import PMTenantSerializer
from .views import _requested_workspace


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def correct_tenant_profile(request, tenant_id):
    workspace = _requested_workspace(request)
    tenant = PMTenant.objects.select_for_update().filter(workspace=workspace, pk=tenant_id).first()
    if not tenant:
        return Response({"detail": "Tenant not found in the active portfolio."}, status=status.HTTP_404_NOT_FOUND)

    property_id = request.data.get("property_id")
    unit_id = request.data.get("unit_id")
    property_obj = PMProperty.objects.filter(workspace=workspace, pk=property_id).first() if property_id else None
    if property_id and not property_obj:
        return Response({"detail": "Choose a valid property."}, status=status.HTTP_400_BAD_REQUEST)
    unit = PMUnit.objects.filter(workspace=workspace, property=property_obj, pk=unit_id).first() if unit_id and property_obj else None
    if unit_id and not unit:
        return Response({"detail": "Choose a valid unit for this property."}, status=status.HTTP_400_BAD_REQUEST)

    old_email = (tenant.email or "").lower()
    tenant_payload = {
        key: request.data.get(key)
        for key in ("first_name", "last_name", "email", "phone", "move_in_date", "lease_start", "lease_end", "monthly_rent", "notes")
        if key in request.data
    }
    if property_obj:
        tenant_payload["property_name"] = property_obj.name
        tenant_payload["unit_label"] = unit.label if unit else ""

    serializer = PMTenantSerializer(tenant, data=tenant_payload, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    tenant = serializer.save()

    active = PMOccupancy.objects.select_for_update().filter(
        workspace=workspace,
        tenant=tenant,
        status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN],
    ).order_by("-move_in_date", "-id").first()

    if property_obj:
        previous_unit = active.unit if active else None
        if active:
            active.property = property_obj
            active.unit = unit
            active.move_in_date = request.data.get("move_in_date") or tenant.move_in_date or active.move_in_date
            active.notes = str(request.data.get("occupancy_notes") or active.notes or "")
            active.save(update_fields=["property", "unit", "move_in_date", "notes", "updated_at"])
        else:
            active = PMOccupancy.objects.create(
                workspace=workspace,
                tenant=tenant,
                property=property_obj,
                unit=unit,
                status=PMOccupancy.Status.ACTIVE,
                move_in_date=request.data.get("move_in_date") or tenant.move_in_date or timezone.localdate(),
                notes=str(request.data.get("occupancy_notes") or "Corrected from tenant profile."),
                created_by=request.user,
            )
        if previous_unit and previous_unit.id != (unit.id if unit else None):
            previous_unit.availability = PMUnit.Availability.AVAILABLE
            previous_unit.save(update_fields=["availability", "updated_at"])
        if unit:
            unit.availability = PMUnit.Availability.OCCUPIED
            unit.save(update_fields=["availability", "updated_at"])

    lease = tenant.leases.exclude(status="ENDED").order_by("-start_date", "-id").first()
    if lease:
        field_map = {
            "start_date": "lease_start",
            "end_date": "lease_end",
            "monthly_rent": "monthly_rent",
            "security_deposit": "security_deposit",
            "housing_authority": "housing_authority",
            "tenant_portion": "tenant_portion",
            "assistance_portion": "assistance_portion",
        }
        changed = []
        for field, request_key in field_map.items():
            if request_key in request.data:
                value = request.data.get(request_key)
                setattr(lease, field, value if value != "" else None)
                changed.append(field)
        if "section8" in request.data:
            lease.section8 = bool(request.data.get("section8"))
            changed.append("section8")
        if unit_id is not None:
            lease.unit = unit
            changed.append("unit")
        if changed:
            lease.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))

    email_changed = (tenant.email or "").lower() != old_email
    if email_changed:
        tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).update(
            status=PMTenantInvitation.Status.REVOKED,
            revoked_at=timezone.now(),
        )
        tenant.status = PMTenant.Status.DRAFT
        tenant.save(update_fields=["status", "updated_at"])

    data = PMTenantSerializer(tenant).data
    data.update({
        "detail": "Tenant information corrected without replacing the tenant record.",
        "email_changed": email_changed,
        "active_occupancy_id": active.id if active else None,
    })
    return Response(data)
