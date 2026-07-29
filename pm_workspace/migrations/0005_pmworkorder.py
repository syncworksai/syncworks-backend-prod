from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0004_pm_leasing_ledger_foundation"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMWorkOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("CALL_IN", "Call-in request"), ("OFFICE", "Office entered"), ("TENANT_PORTAL", "Tenant portal"), ("INSPECTION", "Inspection"), ("PREVENTIVE", "Preventive maintenance")], default="CALL_IN", max_length=24)),
                ("category", models.CharField(max_length=40)),
                ("issue_type", models.CharField(blank=True, max_length=100)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField()),
                ("priority", models.CharField(choices=[("ROUTINE", "Routine"), ("HIGH", "High"), ("URGENT", "Urgent"), ("EMERGENCY", "Emergency")], default="ROUTINE", max_length=16)),
                ("status", models.CharField(choices=[("NEW", "New"), ("TRIAGE", "Triage"), ("ASSIGNED", "Assigned"), ("MARKETPLACE", "Marketplace"), ("SCHEDULED", "Scheduled"), ("IN_PROGRESS", "In progress"), ("WAITING_PARTS", "Waiting on parts"), ("WAITING_APPROVAL", "Waiting approval"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="NEW", max_length=24)),
                ("dispatch_mode", models.CharField(choices=[("UNASSIGNED", "Unassigned"), ("INTERNAL", "Internal team"), ("VENDOR", "Known vendor"), ("MARKETPLACE", "SyncWorks marketplace")], default="UNASSIGNED", max_length=24)),
                ("caller_name", models.CharField(blank=True, max_length=180)),
                ("caller_phone", models.CharField(blank=True, max_length=40)),
                ("permission_to_enter", models.BooleanField(default=False)),
                ("pets_or_access_notes", models.TextField(blank=True)),
                ("preferred_schedule", models.CharField(blank=True, max_length=180)),
                ("water_shutoff", models.BooleanField(default=False)),
                ("electrical_hazard", models.BooleanField(default=False)),
                ("active_leak", models.BooleanField(default=False)),
                ("no_heat_or_air", models.BooleanField(default=False)),
                ("appliance_make_model", models.CharField(blank=True, max_length=180)),
                ("internal_assignee", models.CharField(blank=True, max_length=180)),
                ("vendor_name", models.CharField(blank=True, max_length=180)),
                ("vendor_email", models.EmailField(blank=True, max_length=254)),
                ("vendor_phone", models.CharField(blank=True, max_length=40)),
                ("not_to_exceed", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("marketplace_ticket_id", models.PositiveBigIntegerField(blank=True, db_index=True, null=True)),
                ("marketplace_requested_at", models.DateTimeField(blank=True, null=True)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_hub_work_orders", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="work_orders", to="pm_workspace.pmproperty")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="pm_workspace.pmtenant")),
                ("unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="pm_workspace.pmunit")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="work_orders", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(model_name="pmworkorder", index=models.Index(fields=["workspace", "status"], name="pm_wo_ws_status_idx")),
        migrations.AddIndex(model_name="pmworkorder", index=models.Index(fields=["workspace", "property", "status"], name="pm_wo_prop_status_idx")),
        migrations.AddIndex(model_name="pmworkorder", index=models.Index(fields=["workspace", "priority"], name="pm_wo_ws_priority_idx")),
    ]
