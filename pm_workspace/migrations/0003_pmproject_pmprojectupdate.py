from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0002_pmproperty"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("unit_label", models.CharField(blank=True, max_length=80)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("category", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(choices=[("REQUESTED", "Requested"), ("PLANNING", "Planning"), ("APPROVAL", "Quotes and approvals"), ("SCHEDULED", "Scheduled"), ("IN_PROGRESS", "In progress"), ("REVIEW", "Inspection or review"), ("COMPLETED", "Completed"), ("ARCHIVED", "Archived")], default="REQUESTED", max_length=24)),
                ("priority", models.CharField(choices=[("LOW", "Low"), ("NORMAL", "Normal"), ("HIGH", "High"), ("URGENT", "Urgent")], default="NORMAL", max_length=16)),
                ("progress_percent", models.PositiveSmallIntegerField(default=0)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("target_date", models.DateField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("assignment_type", models.CharField(choices=[("INTERNAL", "Internal"), ("EXTERNAL", "External"), ("UNASSIGNED", "Unassigned")], default="UNASSIGNED", max_length=16)),
                ("internal_assignee_name", models.CharField(blank=True, max_length=180)),
                ("internal_assignee_email", models.EmailField(blank=True, max_length=254)),
                ("external_assignee_name", models.CharField(blank=True, max_length=180)),
                ("external_assignee_email", models.EmailField(blank=True, max_length=254)),
                ("vendor_title", models.CharField(blank=True, max_length=180)),
                ("vendor_contact_name", models.CharField(blank=True, max_length=180)),
                ("vendor_email", models.EmailField(blank=True, max_length=254)),
                ("contract_reference", models.CharField(blank=True, max_length=180)),
                ("budget_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("actual_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("blocker", models.TextField(blank=True)),
                ("next_action", models.TextField(blank=True)),
                ("next_action_due", models.DateField(blank=True, null=True)),
                ("update_recipient_emails", models.TextField(blank=True)),
                ("custom_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_projects", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="projects", to="pm_workspace.pmproperty")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projects", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PMProjectUpdate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.TextField()),
                ("status", models.CharField(blank=True, choices=[("REQUESTED", "Requested"), ("PLANNING", "Planning"), ("APPROVAL", "Quotes and approvals"), ("SCHEDULED", "Scheduled"), ("IN_PROGRESS", "In progress"), ("REVIEW", "Inspection or review"), ("COMPLETED", "Completed"), ("ARCHIVED", "Archived")], max_length=24)),
                ("progress_percent", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("blocker", models.TextField(blank=True)),
                ("next_action", models.TextField(blank=True)),
                ("next_action_due", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pm_project_updates", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="updates", to="pm_workspace.pmproject")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(model_name="pmproject", index=models.Index(fields=["workspace", "status"], name="pm_workspac_workspa_b53f22_idx")),
        migrations.AddIndex(model_name="pmproject", index=models.Index(fields=["workspace", "target_date"], name="pm_workspac_workspa_631f64_idx")),
    ]
