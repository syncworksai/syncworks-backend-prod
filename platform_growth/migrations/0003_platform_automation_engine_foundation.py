# platform_growth/migrations/0003_platform_automation_engine_foundation.py
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_growth", "0002_phase4b_growth_os"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAutomationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("trigger_type", models.CharField(choices=[("lead_created", "Lead Created"), ("lead_status_changed", "Lead Status Changed"), ("ticket_completed", "Ticket Completed"), ("inbound_message_received", "Inbound Message Received"), ("content_draft_created", "Content Draft Created")], max_length=64)),
                ("action_type", models.CharField(choices=[("create_follow_up_task", "Create Follow-up Task"), ("generate_message_draft", "Generate Message Draft"), ("generate_social_post_draft", "Generate Social Post Draft"), ("add_lead_to_pipeline", "Add Lead To Pipeline"), ("log_activation_event", "Log Activation Event")], max_length=64)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("PAUSED", "Paused"), ("ARCHIVED", "Archived")], default="DRAFT", max_length=20)),
                ("conditions", models.JSONField(blank=True, default=dict)),
                ("action_config", models.JSONField(blank=True, default=dict)),
                ("is_system_template", models.BooleanField(default=False)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name", "-created_at"]},
        ),
        migrations.CreateModel(
            name="PlatformAutomationExecution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trigger_type", models.CharField(max_length=64)),
                ("trigger_payload", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("QUEUED", "Queued"), ("COMPLETED", "Completed"), ("FAILED", "Failed"), ("SKIPPED", "Skipped")], default="QUEUED", max_length=20)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="executions", to="platform_growth.platformautomationrule")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]