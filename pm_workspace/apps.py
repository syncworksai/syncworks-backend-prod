from decimal import Decimal

from django.apps import AppConfig


class PMWorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pm_workspace"
    verbose_name = "Property Management Workspaces"

    def ready(self):
        from django.db.models import Q
        from rest_framework import status
        from rest_framework.exceptions import ValidationError
        from rest_framework.response import Response

        from . import communication_models, document_models, lifecycle_models, owner_models, property_profile_models, workorder_models  # noqa: F401
        from .lifecycle_models import PMOccupancy
        from .models import PMLedgerEntry, PMProperty, PMTenant, PMUnit
        from .serializers import PMProjectSerializer, PMPropertySerializer, PMTenantSerializer
        from .views import PMProjectViewSet

        if not getattr(PMProjectSerializer, "_syncworks_blank_normalizer", False):
            original_project_to_internal = PMProjectSerializer.to_internal_value

            def project_to_internal_value(serializer, data):
                normalized = data.copy() if hasattr(data, "copy") else dict(data or {})
                for field in ("property", "start_date", "target_date", "next_action_due", "budget_amount", "actual_amount"):
                    if normalized.get(field) == "":
                        normalized[field] = None
                if normalized.get("progress_percent") in ("", None):
                    normalized["progress_percent"] = 0
                for field in ("title", "description", "category", "unit_label", "internal_assignee_name", "internal_assignee_email", "external_assignee_name", "external_assignee_email", "vendor_title", "vendor_contact_name", "vendor_email", "contract_reference", "blocker", "next_action", "update_recipient_emails"):
                    if isinstance(normalized.get(field), str):
                        normalized[field] = normalized[field].strip()
                return original_project_to_internal(serializer, normalized)

            PMProjectSerializer.to_internal_value = project_to_internal_value
            PMProjectSerializer._syncworks_blank_normalizer = True

        if not getattr(PMTenantSerializer, "_syncworks_property_resolver", False):
            original_tenant_representation = PMTenantSerializer.to_representation

            def tenant_to_representation(serializer, instance):
                data = original_tenant_representation(serializer, instance)
                occupancy = PMOccupancy.objects.filter(
                    workspace_id=instance.workspace_id,
                    tenant_id=instance.id,
                    status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN],
                ).select_related("property", "unit").order_by("-move_in_date", "-id").first()
                if occupancy:
                    data["property_name"] = occupancy.property.name
                    data["property_id"] = occupancy.property_id
                    data["property_address"] = occupancy.property.address
                    data["unit_label"] = occupancy.unit.label if occupancy.unit else data.get("unit_label", "")
                    data["active_occupancy_id"] = occupancy.id
                else:
                    label = str(data.get("property_name") or "").strip()
                    if label:
                        matched = PMProperty.objects.filter(workspace_id=instance.workspace_id).filter(Q(name__iexact=label) | Q(address__iexact=label)).order_by("id").first()
                        if matched:
                            data["property_name"] = matched.name
                            data["property_id"] = matched.id
                            data["property_address"] = matched.address
                return data

            PMTenantSerializer.to_representation = tenant_to_representation
            PMTenantSerializer._syncworks_property_resolver = True

        if not getattr(PMPropertySerializer, "_syncworks_live_property_metrics", False):
            original_property_representation = PMPropertySerializer.to_representation

            def property_to_representation(serializer, instance):
                data = original_property_representation(serializer, instance)
                active_occupancies = PMOccupancy.objects.filter(
                    workspace_id=instance.workspace_id,
                    property_id=instance.id,
                    status__in=[PMOccupancy.Status.ACTIVE, PMOccupancy.Status.NOTICE_GIVEN],
                ).select_related("tenant", "unit")
                tenant_ids = list(active_occupancies.values_list("tenant_id", flat=True))
                units = PMUnit.objects.filter(property_id=instance.id)
                total_units = units.count()
                occupied_unit_ids = set(active_occupancies.exclude(unit_id=None).values_list("unit_id", flat=True))
                occupied_units = len(occupied_unit_ids)

                effective_total = total_units or 1
                effective_occupied = occupied_units
                if total_units == 0 and tenant_ids:
                    effective_occupied = 1
                elif total_units and tenant_ids and effective_occupied == 0:
                    effective_occupied = min(len(set(tenant_ids)), total_units)
                available_units = max(effective_total - effective_occupied, 0)

                balance = Decimal("0.00")
                if tenant_ids:
                    for ledger_entry in PMLedgerEntry.objects.filter(tenant_id__in=tenant_ids):
                        if ledger_entry.entry_type in {PMLedgerEntry.EntryType.PAYMENT, PMLedgerEntry.EntryType.CREDIT}:
                            balance -= ledger_entry.amount
                        else:
                            balance += ledger_entry.amount

                occupancy_rate = Decimal(effective_occupied) / Decimal(effective_total) if effective_total else Decimal("0")
                data.update({
                    "tenant_count": len(set(tenant_ids)),
                    "total_units": total_units,
                    "occupied_units": effective_occupied,
                    "available_units": available_units,
                    "occupancy_rate": float(occupancy_rate.quantize(Decimal("0.0001"))),
                    "balance_due": str(balance.quantize(Decimal("0.01"))),
                    "occupancy_status": "OCCUPIED" if effective_occupied else "VACANT",
                })
                return data

            PMPropertySerializer.to_representation = property_to_representation
            PMPropertySerializer._syncworks_live_property_metrics = True

        if not getattr(PMProjectViewSet, "_syncworks_detailed_create_errors", False):
            original_project_create = PMProjectViewSet.create

            def project_create(viewset, request, *args, **kwargs):
                try:
                    return original_project_create(viewset, request, *args, **kwargs)
                except ValidationError as exc:
                    detail = exc.detail
                    parts = []
                    if isinstance(detail, dict):
                        for field, values in detail.items():
                            values = values if isinstance(values, (list, tuple)) else [values]
                            for value in values:
                                parts.append(f"{str(field).replace('_', ' ')}: {value}")
                    elif isinstance(detail, (list, tuple)):
                        parts.extend(str(value) for value in detail)
                    else:
                        parts.append(str(detail))
                    return Response({"detail": " · ".join(parts) or "Project validation failed.", "errors": detail}, status=status.HTTP_400_BAD_REQUEST)

            PMProjectViewSet.create = project_create
            PMProjectViewSet._syncworks_detailed_create_errors = True
