from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .lifecycle_models import PMOccupancy
from .models import PMDocumentPacket, PMLedgerEntry, PMLease, PMProspect, PMTenant, PMUnit, PMWorkspace
from .serializers import (
    PMDocumentPacketSerializer,
    PMLedgerEntrySerializer,
    PMLeaseSerializer,
    PMProspectSerializer,
    PMTenantSerializer,
    PMUnitSerializer,
)


def requested_workspace(request):
    workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
    if not workspace_id and isinstance(request.data, dict):
        workspace_id = request.data.get("workspace_id")
    qs = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    workspace = qs.filter(pk=workspace_id).first() if workspace_id else qs.order_by("id").first()
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


class PMUnitViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMUnitSerializer

    def get_queryset(self):
        workspace = requested_workspace(self.request)
        qs = PMUnit.objects.filter(workspace=workspace).select_related("property")
        availability = str(self.request.query_params.get("availability") or "").strip().upper()
        if availability:
            qs = qs.filter(availability=availability)
        available_only = str(self.request.query_params.get("available_only") or "false").lower() == "true"
        if available_only:
            qs = qs.filter(availability__in=[PMUnit.Availability.AVAILABLE, PMUnit.Availability.NOTICE_GIVEN, PMUnit.Availability.MAKE_READY])
        search = str(self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(label__icontains=search) | Q(property__name__icontains=search) | Q(property__address__icontains=search))
        section8 = str(self.request.query_params.get("section8") or "").lower()
        if section8 in {"true", "false"}:
            qs = qs.filter(accepts_section8=section8 == "true")
        return qs.order_by("property__name", "label")

    def perform_create(self, serializer):
        workspace = requested_workspace(self.request)
        property_obj = serializer.validated_data["property"]
        if property_obj.workspace_id != workspace.id:
            raise ValidationError({"property": "Property is not in the selected portfolio."})
        serializer.save(workspace=workspace)


class PMProspectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMProspectSerializer

    def get_queryset(self):
        workspace = requested_workspace(self.request)
        qs = PMProspect.objects.filter(workspace=workspace).select_related("assigned_unit", "assigned_unit__property")
        stage = str(self.request.query_params.get("stage") or "").strip().upper()
        if stage:
            qs = qs.filter(stage=stage)
        search = str(self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search) | Q(phone__icontains=search))
        return qs.order_by("-updated_at", "-id")

    def perform_create(self, serializer):
        serializer.save(workspace=requested_workspace(self.request), created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="mark-application-sent")
    def mark_application_sent(self, request, pk=None):
        prospect = self.get_object()
        prospect.stage = PMProspect.Stage.APPLICATION_SENT
        prospect.application_sent_at = timezone.now()
        prospect.save(update_fields=["stage", "application_sent_at", "updated_at"])
        return Response(self.get_serializer(prospect).data)

    @action(detail=True, methods=["post"], url_path="schedule-showing")
    def schedule_showing(self, request, pk=None):
        prospect = self.get_object()
        showing_at = request.data.get("showing_at")
        if not showing_at:
            raise ValidationError({"showing_at": "Choose a showing date and time."})
        serializer = self.get_serializer(prospect, data={"showing_at": showing_at, "stage": PMProspect.Stage.SHOWING_SCHEDULED}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="convert-to-tenant")
    @transaction.atomic
    def convert_to_tenant(self, request, pk=None):
        prospect = self.get_object()
        if prospect.stage not in {PMProspect.Stage.APPROVED, PMProspect.Stage.SHOWING_SCHEDULED, PMProspect.Stage.READY_FOR_ONBOARDING}:
            raise ValidationError({"detail": "Approve the prospect before onboarding."})
        if PMTenant.objects.filter(workspace=prospect.workspace, email__iexact=prospect.email).exists():
            raise ValidationError({"email": "A tenant with this email already exists in this portfolio."})
        unit = prospect.assigned_unit
        tenant = PMTenant.objects.create(
            workspace=prospect.workspace,
            first_name=prospect.first_name,
            last_name=prospect.last_name,
            email=prospect.email.lower(),
            phone=prospect.phone,
            property_name=unit.property.name if unit else "",
            unit_label=unit.label if unit else "",
            move_in_date=prospect.desired_move_in,
            created_by=request.user,
            notes=prospect.notes,
        )
        prospect.stage = PMProspect.Stage.CONVERTED
        prospect.save(update_fields=["stage", "updated_at"])
        if unit:
            unit.availability = PMUnit.Availability.OCCUPIED
            unit.save(update_fields=["availability", "updated_at"])
        return Response(PMTenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


class PMLeaseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMLeaseSerializer

    def get_queryset(self):
        workspace = requested_workspace(self.request)
        qs = PMLease.objects.filter(workspace=workspace).select_related("tenant", "unit", "unit__property")
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs.order_by("-start_date", "-id")

    @transaction.atomic
    def perform_create(self, serializer):
        workspace = requested_workspace(self.request)
        tenant = serializer.validated_data["tenant"]
        if tenant.workspace_id != workspace.id:
            raise ValidationError({"tenant": "Tenant is not in the selected portfolio."})
        lease = serializer.save(workspace=workspace)
        tenant.lease_start = lease.start_date
        tenant.lease_end = lease.end_date
        tenant.monthly_rent = lease.monthly_rent
        if lease.unit:
            active_occupancy = PMOccupancy.objects.select_for_update().filter(
                workspace=workspace,
                tenant=tenant,
                status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN],
            ).order_by("-move_in_date", "-id").first()
            previous_unit = active_occupancy.unit if active_occupancy else None

            tenant.property_name = lease.unit.property.name
            tenant.unit_label = lease.unit.label
            if active_occupancy:
                active_occupancy.property = lease.unit.property
                active_occupancy.unit = lease.unit
                active_occupancy.lease = lease
                active_occupancy.status = PMOccupancy.Status.ACTIVE
                active_occupancy.move_in_date = tenant.move_in_date or lease.start_date
                active_occupancy.save(update_fields=[
                    "property",
                    "unit",
                    "lease",
                    "status",
                    "move_in_date",
                    "updated_at",
                ])
            else:
                PMOccupancy.objects.create(
                    workspace=workspace,
                    tenant=tenant,
                    property=lease.unit.property,
                    unit=lease.unit,
                    lease=lease,
                    status=PMOccupancy.Status.ACTIVE,
                    move_in_date=tenant.move_in_date or lease.start_date,
                    notes="Created from tenant lease onboarding.",
                    created_by=self.request.user,
                )

            if previous_unit and previous_unit.id != lease.unit_id:
                previous_unit.availability = PMUnit.Availability.AVAILABLE
                previous_unit.save(update_fields=["availability", "updated_at"])
            lease.unit.availability = PMUnit.Availability.OCCUPIED
            lease.unit.save(update_fields=["availability", "updated_at"])
        tenant.save(update_fields=["lease_start", "lease_end", "monthly_rent", "property_name", "unit_label", "updated_at"])


class PMDocumentPacketViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMDocumentPacketSerializer

    def get_queryset(self):
        return PMDocumentPacket.objects.filter(workspace=requested_workspace(self.request)).select_related("tenant", "prospect", "lease")

    def perform_create(self, serializer):
        serializer.save(workspace=requested_workspace(self.request))

    @action(detail=True, methods=["post"], url_path="mark-sent")
    def mark_sent(self, request, pk=None):
        packet = self.get_object()
        packet.status = PMDocumentPacket.Status.SENT
        packet.sent_at = timezone.now()
        packet.save(update_fields=["status", "sent_at", "updated_at"])
        return Response(self.get_serializer(packet).data)


class PMLedgerEntryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMLedgerEntrySerializer

    def get_queryset(self):
        workspace = requested_workspace(self.request)
        qs = PMLedgerEntry.objects.filter(workspace=workspace).select_related("tenant", "lease")
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs.order_by("-entry_date", "-id")

    def perform_create(self, serializer):
        workspace = requested_workspace(self.request)
        tenant = serializer.validated_data["tenant"]
        if tenant.workspace_id != workspace.id:
            raise ValidationError({"tenant": "Tenant is not in the selected portfolio."})
        serializer.save(workspace=workspace, created_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        workspace = requested_workspace(request)
        entries = PMLedgerEntry.objects.filter(workspace=workspace).select_related("tenant")
        balances = {}
        names = {}
        for entry in entries:
            names[entry.tenant_id] = f"{entry.tenant.first_name} {entry.tenant.last_name}".strip()
            balances.setdefault(entry.tenant_id, Decimal("0.00"))
            if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT}:
                balances[entry.tenant_id] += entry.amount
            else:
                balances[entry.tenant_id] -= entry.amount
        rows = [{"tenant_id": tenant_id, "tenant_name": names[tenant_id], "balance": str(balance.quantize(Decimal('0.01')))} for tenant_id, balance in balances.items()]
        rows.sort(key=lambda row: Decimal(row["balance"]), reverse=True)
        total_due = sum((Decimal(row["balance"]) for row in rows if Decimal(row["balance"]) > 0), Decimal("0.00"))
        return Response({"total_due": str(total_due.quantize(Decimal('0.01'))), "tenants": rows})
