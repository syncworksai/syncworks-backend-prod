from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_existing_occupancies(apps, schema_editor):
    PMTenant = apps.get_model("pm_workspace", "PMTenant")
    PMProperty = apps.get_model("pm_workspace", "PMProperty")
    PMUnit = apps.get_model("pm_workspace", "PMUnit")
    PMLease = apps.get_model("pm_workspace", "PMLease")
    PMOccupancy = apps.get_model("pm_workspace", "PMOccupancy")

    for tenant in PMTenant.objects.exclude(property_name="").iterator():
        label = str(tenant.property_name or "").strip()
        if not label:
            continue
        property_obj = PMProperty.objects.filter(workspace_id=tenant.workspace_id, name__iexact=label).first()
        if not property_obj:
            property_obj = PMProperty.objects.filter(workspace_id=tenant.workspace_id, address__iexact=label).first()
        if not property_obj:
            continue
        unit = None
        if tenant.unit_label:
            unit = PMUnit.objects.filter(property_id=property_obj.id, label__iexact=str(tenant.unit_label).strip()).first()
        lease = PMLease.objects.filter(workspace_id=tenant.workspace_id, tenant_id=tenant.id).order_by("-start_date", "-id").first()
        PMOccupancy.objects.get_or_create(
            workspace_id=tenant.workspace_id,
            tenant_id=tenant.id,
            property_id=property_obj.id,
            status="ACTIVE",
            defaults={
                "unit_id": unit.id if unit else None,
                "lease_id": lease.id if lease else None,
                "move_in_date": tenant.move_in_date or tenant.lease_start,
                "notes": "Backfilled from existing tenant-property assignment.",
            },
        )
        if unit and unit.availability != "OCCUPIED":
            unit.availability = "OCCUPIED"
            unit.save(update_fields=["availability"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0008_pmpropertydocument"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMOccupancy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending move-in"), ("ACTIVE", "Active"), ("NOTICE_GIVEN", "Notice given"), ("MOVED_OUT", "Moved out"), ("EVICTED", "Evicted")], default="ACTIVE", max_length=20)),
                ("move_in_date", models.DateField(blank=True, null=True)),
                ("notice_date", models.DateField(blank=True, null=True)),
                ("move_out_date", models.DateField(blank=True, null=True)),
                ("move_out_reason", models.CharField(blank=True, max_length=180)),
                ("forwarding_address", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_occupancies", to=settings.AUTH_USER_MODEL)),
                ("lease", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="occupancies", to="pm_workspace.pmlease")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="occupancies", to="pm_workspace.pmproperty")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="occupancies", to="pm_workspace.pmtenant")),
                ("unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="occupancies", to="pm_workspace.pmunit")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="occupancies", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-move_in_date", "-id"]},
        ),
        migrations.CreateModel(
            name="PMTenantCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("case_type", models.CharField(choices=[("EVICTION", "Eviction"), ("COLLECTIONS", "Collections"), ("LEGAL", "Legal"), ("PAYMENT_PLAN", "Payment plan")], max_length=24)),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("NOTICE_SENT", "Notice sent"), ("FILED", "Filed"), ("JUDGMENT", "Judgment"), ("SENT_TO_COLLECTIONS", "Sent to collections"), ("PAYMENT_PLAN", "Payment plan"), ("CLOSED", "Closed")], default="OPEN", max_length=32)),
                ("opened_date", models.DateField()),
                ("filed_date", models.DateField(blank=True, null=True)),
                ("judgment_date", models.DateField(blank=True, null=True)),
                ("collections_sent_date", models.DateField(blank=True, null=True)),
                ("agency_name", models.CharField(blank=True, max_length=180)),
                ("agency_email", models.EmailField(blank=True, max_length=254)),
                ("balance_at_open", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("current_balance", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("reference", models.CharField(blank=True, max_length=180)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_tenant_cases", to=settings.AUTH_USER_MODEL)),
                ("occupancy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cases", to="pm_workspace.pmoccupancy")),
                ("property", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tenant_cases", to="pm_workspace.pmproperty")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cases", to="pm_workspace.pmtenant")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_cases", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-opened_date", "-id"]},
        ),
        migrations.AddField(model_name="pmconversation", name="internal_only", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="pmconversation", name="lease", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmlease")),
        migrations.AddField(model_name="pmconversation", name="property", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmproperty")),
        migrations.AddField(model_name="pmconversation", name="tenant_case", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmtenantcase")),
        migrations.AddField(model_name="pmconversation", name="work_order", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmworkorder")),
        migrations.AlterField(model_name="pmconversation", name="category", field=models.CharField(choices=[("TENANT", "Tenant"), ("INVESTOR", "Investor"), ("MAINTENANCE", "Maintenance"), ("INTERNAL", "Internal team"), ("COLLECTIONS", "Collections and legal")], max_length=20)),
        migrations.AlterField(model_name="pmconversation", name="property_owner", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmpropertyowner")),
        migrations.AlterField(model_name="pmconversation", name="tenant", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="pm_workspace.pmtenant")),
        migrations.AlterField(model_name="pmconversationmessage", name="sender_role", field=models.CharField(choices=[("PM", "Property management"), ("TENANT", "Tenant"), ("INVESTOR", "Investor"), ("INTERNAL", "Internal team"), ("SYSTEM", "System")], max_length=16)),
        migrations.RunPython(backfill_existing_occupancies, migrations.RunPython.noop),
        migrations.AddIndex(model_name="pmoccupancy", index=models.Index(fields=["workspace", "property", "status"], name="pm_workspac_workspa_4c4553_idx")),
        migrations.AddIndex(model_name="pmoccupancy", index=models.Index(fields=["workspace", "tenant", "status"], name="pm_workspac_workspa_950a50_idx")),
        migrations.AddIndex(model_name="pmtenantcase", index=models.Index(fields=["workspace", "status"], name="pm_workspac_workspa_f19478_idx")),
        migrations.AddIndex(model_name="pmtenantcase", index=models.Index(fields=["workspace", "tenant"], name="pm_workspac_workspa_7a968c_idx")),
        migrations.AddIndex(model_name="pmconversation", index=models.Index(fields=["workspace", "category", "status"], name="pm_workspac_workspa_b98aec_idx")),
    ]
