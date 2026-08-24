from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_twilio_backlog(apps, schema_editor):
    Backlog = apps.get_model("user_accounts", "PlatformBuildBacklogItem")
    Backlog.objects.get_or_create(
        title="Bring-your-own Twilio SMS/MMS connector",
        defaults={
            "status": "BUILD_LATER",
            "priority": "HIGH",
            "module": "Communications / SYNC Inbox",
            "source": "ChatGPT",
            "notes": "Allow a user/business to connect its own Twilio account or Messaging Service to SyncWorks. Ingest SMS/MMS, match contacts, classify with SYNC Assist, route to the correct Personal/Business/PM destination, preserve threads, support replies and delivery status, and validate Twilio webhook signatures. Include consent/STOP/HELP and A2P setup guidance.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0132_stripe_webhook_event"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformuserclassification",
            name="intelligence",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="God Mode roles, module access, subscription state, acquisition attribution, customer attribution and value metadata.",
            ),
        ),
        migrations.CreateModel(
            name="PlatformBuildBacklogItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("status", models.CharField(choices=[("IDEA", "Idea"), ("BUILD_LATER", "Build later"), ("NEXT", "Next"), ("IN_PROGRESS", "In progress"), ("TESTING", "Testing"), ("DONE", "Done")], db_index=True, default="BUILD_LATER", max_length=24)),
                ("priority", models.CharField(choices=[("URGENT", "Urgent"), ("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")], db_index=True, default="MEDIUM", max_length=16)),
                ("module", models.CharField(blank=True, db_index=True, default="General", max_length=120)),
                ("source", models.CharField(blank=True, default="God Mode", max_length=120)),
                ("notes", models.TextField(blank=True, default="")),
                ("github_issue_number", models.PositiveIntegerField(blank=True, null=True, unique=True)),
                ("github_url", models.URLField(blank=True, default="")),
                ("github_sync_error", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_backlog_items_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_backlog_items_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="platformbuildbacklogitem",
            index=models.Index(fields=["status", "priority"], name="ua_backlog_status_priority_idx"),
        ),
        migrations.AddIndex(
            model_name="platformbuildbacklogitem",
            index=models.Index(fields=["module", "updated_at"], name="ua_backlog_module_updated_idx"),
        ),
        migrations.RunPython(seed_twilio_backlog, migrations.RunPython.noop),
    ]
