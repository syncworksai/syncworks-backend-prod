from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Ticket

from .models import PMProperty, PMTenant, PMUnit
from .views import _requested_workspace
from .workorder_models import PMWorkOrder


class PMWorkOrderSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    tenant_name = serializers.SerializerMethodField()
    marketplace_ticket_code = serializers.SerializerMethodField()

    class Meta:
        model = PMWorkOrder
        fields = "__all__"
        read_only_fields = (
            "id", "workspace", "created_by", "created_at", "updated_at",
            "marketplace_ticket_id", "marketplace_requested_at", "completed_at",
            "property_name", "unit_label", "tenant_name", "marketplace_ticket_code",
        )

    def get_tenant_name(self, obj):
        if not obj.tenant:
            return ""
        return f"{obj.tenant.first_name} {obj.tenant.last_name}".strip()

    def get_marketplace_ticket_code(self, obj):
        return f"MP-{obj.marketplace_ticket_id:06d}" if obj.marketplace_ticket_id else ""

    def to_internal_value(self, data):
        normalized = data.copy() if hasattr(data, "copy") else dict(data)
        for field in ("unit", "tenant", "not_to_exceed", "scheduled_for"):
            if normalized.get(field) == "":
                normalized[field] = None
        return super().to_internal_value(normalized)

    def validate(self, attrs):
        request = self.context.get("request")
        workspace = _requested_workspace(request) if request else None
        prop = attrs.get("property") or getattr(self.instance, "property", None)
        unit = attrs.get("unit") if "unit" in attrs else getattr(self.instance, "unit", None)
        tenant = attrs.get("tenant") if "tenant" in attrs else getattr(self.instance, "tenant", None)
        if prop and workspace and prop.workspace_id != workspace.id:
            raise serializers.ValidationError({"property": "Property is not available in this portfolio."})
        if unit and (unit.workspace_id != workspace.id or unit.property_id != prop.id):
            raise serializers.ValidationError({"unit": "Unit must belong to the selected property."})
        if tenant and tenant.workspace_id != workspace.id:
            raise serializers.ValidationError({"tenant": "Tenant is not available in this portfolio."})
        dispatch = attrs.get("dispatch_mode", getattr(self.instance, "dispatch_mode", PMWorkOrder.Dispatch.UNASSIGNED))
        if dispatch == PMWorkOrder.Dispatch.VENDOR and not (attrs.get("vendor_name") or getattr(self.instance, "vendor_name", "")):
            raise serializers.ValidationError({"vendor_name": "Choose or enter a vendor name."})
        return attrs


class PMWorkOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMWorkOrderSerializer

    def get_queryset(self):
        workspace = _requested_workspace(self.request)
        qs = PMWorkOrder.objects.filter(workspace=workspace).select_related("property", "unit", "tenant", "created_by")
        property_id = self.request.query_params.get("property")
        if property_id:
            qs = qs.filter(property_id=property_id)
        status_filter = str(self.request.query_params.get("status") or "").strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(workspace=_requested_workspace(self.request), created_by=self.request.user)

    def perform_update(self, serializer):
        item = serializer.save()
        if item.status == PMWorkOrder.Status.COMPLETED and not item.completed_at:
            item.completed_at = timezone.now()
            item.save(update_fields=["completed_at", "updated_at"])

    @action(detail=True, methods=["post"], url_path="publish-marketplace")
    @transaction.atomic
    def publish_marketplace(self, request, pk=None):
        item = self.get_object()
        if item.marketplace_ticket_id:
            return Response(self.get_serializer(item).data)
        prop = item.property
        hazard_notes = []
        if item.active_leak:
            hazard_notes.append("Active leak")
        if item.electrical_hazard:
            hazard_notes.append("Electrical hazard")
        if item.water_shutoff:
            hazard_notes.append("Water shutoff may be required")
        if item.no_heat_or_air:
            hazard_notes.append("No heat or air conditioning")
        access = "Permission to enter: Yes" if item.permission_to_enter else "Permission to enter: No"
        scope = "\n".join(filter(None, [
            item.description,
            f"Rental maintenance category: {item.category}",
            f"Issue type: {item.issue_type}" if item.issue_type else "",
            f"Property: {prop.name}",
            f"Unit: {item.unit.label}" if item.unit else "",
            access,
            f"Access/pets: {item.pets_or_access_notes}" if item.pets_or_access_notes else "",
            f"Preferred schedule: {item.preferred_schedule}" if item.preferred_schedule else "",
            f"Hazards: {', '.join(hazard_notes)}" if hazard_notes else "",
            f"Not-to-exceed authorization: ${item.not_to_exceed}" if item.not_to_exceed is not None else "Quote required before work.",
        ]))
        ticket = Ticket.objects.create(
            customer=request.user,
            is_marketplace=True,
            status=Ticket.Status.NEW,
            work_title=item.title,
            work_scope=scope,
            service_address=f"{prop.address}, {prop.city}, {prop.state} {prop.zip}",
            service_zip=prop.zip,
            payment_method=Ticket.PaymentMethod.OTHER,
            source_system="SYNCWORKS_PM",
            external_ticket_id=f"PMWO-{item.id}",
        )
        item.dispatch_mode = PMWorkOrder.Dispatch.MARKETPLACE
        item.status = PMWorkOrder.Status.MARKETPLACE
        item.marketplace_ticket_id = ticket.id
        item.marketplace_requested_at = timezone.now()
        item.save(update_fields=["dispatch_mode", "status", "marketplace_ticket_id", "marketplace_requested_at", "updated_at"])
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)
