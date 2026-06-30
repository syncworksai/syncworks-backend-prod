from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0107_operational_events_eta_alerts"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutomationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("trigger_type", models.CharField(choices=[("OPERATIONAL_EVENT", "Operational Event"), ("TICKET_STATUS", "Ticket Status"), ("ETA_DELAYED", "ETA Delayed"), ("MANUAL", "Manual")], max_length=32)),
                ("trigger_config", models.JSONField(blank=True, default=dict)),
                ("action_type", models.CharField(choices=[("CREATE_EVENT", "Create Event"), ("CREATE_REQUIREMENT", "Create Requirement"), ("CREATE_ALERT", "Create Alert"), ("UPDATE_TICKET_STATUS", "Update Ticket Status"), ("CUSTOM", "Custom")], max_length=32)),
                ("action_config", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("priority", models.PositiveIntegerField(default=100)),
                ("stop_processing", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="automation_rules", to="user_accounts.business")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="automation_rules_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["priority", "id"]},
        ),
        migrations.CreateModel(
            name="AutomationExecution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("SUCCEEDED", "Succeeded"), ("SKIPPED", "Skipped"), ("FAILED", "Failed")], default="PENDING", max_length=20)),
                ("dedupe_key", models.CharField(max_length=220)),
                ("input_data", models.JSONField(blank=True, default=dict)),
                ("output_data", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="automation_executions", to="user_accounts.operationalevent")),
                ("executed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="automation_executions_run", to=settings.AUTH_USER_MODEL)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="executions", to="user_accounts.automationrule")),
                ("ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="automation_executions", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="automationrule",
            constraint=models.UniqueConstraint(fields=("business", "name"), name="ua_automation_rule_name_unique"),
        ),
        migrations.AddIndex(
            model_name="automationrule",
            index=models.Index(fields=["business", "trigger_type", "is_active"], name="ua_auto_rule_trigger_idx"),
        ),
        migrations.AddConstraint(
            model_name="automationexecution",
            constraint=models.UniqueConstraint(fields=("rule", "dedupe_key"), name="ua_automation_execution_unique"),
        ),
        migrations.AddIndex(
            model_name="automationexecution",
            index=models.Index(fields=["rule", "status", "created_at"], name="ua_auto_exec_status_idx"),
        ),
    ]
