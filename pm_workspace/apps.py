from django.apps import AppConfig


class PMWorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pm_workspace"
    verbose_name = "Property Management Workspaces"

    def ready(self):
        from django.db.models import Q

        from . import workorder_models  # noqa: F401
        from .models import PMProperty
        from .serializers import PMProjectSerializer, PMTenantSerializer

        if not getattr(PMProjectSerializer, "_syncworks_blank_normalizer", False):
            original_project_to_internal = PMProjectSerializer.to_internal_value

            def project_to_internal_value(serializer, data):
                normalized = data.copy() if hasattr(data, "copy") else dict(data or {})
                for field in (
                    "property",
                    "start_date",
                    "target_date",
                    "next_action_due",
                    "budget_amount",
                    "actual_amount",
                ):
                    if normalized.get(field) == "":
                        normalized[field] = None
                if normalized.get("progress_percent") in ("", None):
                    normalized["progress_percent"] = 0
                for field in (
                    "title",
                    "description",
                    "category",
                    "unit_label",
                    "internal_assignee_name",
                    "internal_assignee_email",
                    "external_assignee_name",
                    "external_assignee_email",
                    "vendor_title",
                    "vendor_contact_name",
                    "vendor_email",
                    "contract_reference",
                    "blocker",
                    "next_action",
                    "update_recipient_emails",
                ):
                    if isinstance(normalized.get(field), str):
                        normalized[field] = normalized[field].strip()
                return original_project_to_internal(serializer, normalized)

            PMProjectSerializer.to_internal_value = project_to_internal_value
            PMProjectSerializer._syncworks_blank_normalizer = True

        if not getattr(PMTenantSerializer, "_syncworks_property_resolver", False):
            original_tenant_representation = PMTenantSerializer.to_representation

            def tenant_to_representation(serializer, instance):
                data = original_tenant_representation(serializer, instance)
                label = str(data.get("property_name") or "").strip()
                if label:
                    matched = (
                        PMProperty.objects.filter(workspace_id=instance.workspace_id)
                        .filter(Q(name__iexact=label) | Q(address__iexact=label))
                        .order_by("id")
                        .first()
                    )
                    if matched:
                        data["property_name"] = matched.name
                        data["property_id"] = matched.id
                        data["property_address"] = matched.address
                return data

            PMTenantSerializer.to_representation = tenant_to_representation
            PMTenantSerializer._syncworks_property_resolver = True
