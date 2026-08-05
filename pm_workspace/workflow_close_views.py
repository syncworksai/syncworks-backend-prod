from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .leasing_views import requested_workspace
from .lifecycle_models import PMOccupancy
from .models import PMTenant, PMUnit
from .record_views import _money_balance, _occupancy_data
from .workflow_views import evict_occupancy


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def close_occupancy_workflow(request, occupancy_id):
    if bool(request.data.get("evicted")):
        return evict_occupancy(request._request, occupancy_id)

    workspace = requested_workspace(request)
    occupancy = PMOccupancy.objects.select_related("tenant", "property", "unit").filter(workspace=workspace, pk=occupancy_id).first()
    if not occupancy:
        return Response({"detail": "Occupancy not found."}, status=status.HTTP_404_NOT_FOUND)

    occupancy.status = PMOccupancy.Status.MOVED_OUT
    occupancy.move_out_date = request.data.get("move_out_date") or timezone.localdate()
    occupancy.move_out_reason = str(request.data.get("move_out_reason") or "Tenant moved out")
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

    # A normal move-out preserves the tenant history. The PM may create a make-ready
    # work order manually or use the dedicated make-ready screen after inspection.
    return Response({
        "detail": "Occupancy closed. Tenant history and ledger were preserved.",
        "occupancy": _occupancy_data(occupancy),
        "tenant_balance": str(_money_balance(tenant)),
    })
