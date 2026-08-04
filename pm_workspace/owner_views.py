from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PMTenant, PMTenantInvitation
from .owner_models import PMPropertyOwner
from .views import _requested_workspace


class PMPropertyOwnerSerializer(serializers.ModelSerializer):
    property_names = serializers.SerializerMethodField()

    class Meta:
        model = PMPropertyOwner
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "property_names")

    def get_property_names(self, obj):
        return list(obj.properties.order_by("name").values_list("name", flat=True))

    def validate_properties(self, values):
        workspace = _requested_workspace(self.context["request"])
        if any(item.workspace_id != workspace.id for item in values):
            raise serializers.ValidationError("Every property must belong to the active portfolio.")
        return values


class PMPropertyOwnerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMPropertyOwnerSerializer

    def get_queryset(self):
        workspace = _requested_workspace(self.request)
        qs = PMPropertyOwner.objects.filter(workspace=workspace).prefetch_related("properties")
        property_id = self.request.query_params.get("property_id")
        if property_id:
            qs = qs.filter(properties__id=property_id)
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(workspace=_requested_workspace(self.request), created_by=self.request.user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def complete_tenant_onboarding_internally(request, tenant_id):
    workspace = _requested_workspace(request)
    tenant = PMTenant.objects.select_for_update().filter(pk=tenant_id, workspace=workspace).first()
    if not tenant:
        return Response({"detail": "Tenant not found in the active portfolio."}, status=status.HTTP_404_NOT_FOUND)

    pending = tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).order_by("-created_at").first()
    if pending:
        pending.status = PMTenantInvitation.Status.REVOKED
        pending.revoked_at = timezone.now()
        pending.save(update_fields=["status", "revoked_at"])

    tenant.status = PMTenant.Status.CONNECTED
    note = str(request.data.get("note") or "Onboarding completed internally by property management.").strip()
    stamp = timezone.localtime().strftime("%Y-%m-%d %I:%M %p")
    audit_line = f"[{stamp}] {note}"
    tenant.notes = f"{tenant.notes}\n{audit_line}".strip()
    tenant.save(update_fields=["status", "notes", "updated_at"])

    return Response({
        "detail": "Tenant onboarding marked complete internally. Portal access can still be invited later.",
        "tenant_id": tenant.id,
        "status": tenant.status,
        "completed_by": request.user.get_full_name() or request.user.email,
        "completed_at": timezone.now(),
    })
