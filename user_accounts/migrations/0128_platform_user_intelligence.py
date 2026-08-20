from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0127_ticket_operational_scheduled_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformuserclassification",
            name="intelligence",
            field=models.JSONField(blank=True, default=dict),
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
    ]
