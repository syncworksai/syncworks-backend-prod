import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0137_business_pilot_tracking"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncAssistJob",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("goal_id", models.UUIDField()),
                ("state", models.CharField(max_length=12, db_index=True, default="QUEUED", choices=[
                    ("QUEUED", "Queued"), ("RUNNING", "Running"), ("WAITING", "Awaiting owner approval"),
                    ("RETRY", "Retry scheduled"), ("SUCCEEDED", "Succeeded"),
                    ("FAILED", "Failed"), ("CANCELLED", "Cancelled"),
                ])),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("max_attempts", models.PositiveSmallIntegerField(default=3)),
                ("next_run_at", models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ("lease_expires_at", models.DateTimeField(null=True, blank=True)),
                ("lease_token", models.UUIDField(null=True, blank=True)),
                ("last_error", models.CharField(max_length=300, blank=True, default="")),
                ("last_receipt_id", models.UUIDField(null=True, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name="sync_assist_jobs")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["state", "next_run_at"], name="ua_sa_job_state_due_idx")],
                "constraints": [models.UniqueConstraint(fields=["owner", "goal_id"], name="ua_sa_job_owner_goal_uniq")],
            },
        ),
    ]
