import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0138_sync_assist_job"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="FreelanceSyntheticJob",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("project_id", models.UUIDField(null=True, blank=True)),
                ("state", models.CharField(max_length=12, db_index=True, default="QUEUED", choices=[
                    ("QUEUED", "Queued"), ("RUNNING", "Running"), ("REVIEW", "Review needed"),
                    ("APPROVED", "Approved"), ("FAILED", "Failed"), ("CANCELLED", "Cancelled"),
                ])),
                ("row_count", models.PositiveSmallIntegerField(default=500)),
                ("seed", models.PositiveIntegerField(default=42)),
                ("result", models.JSONField(default=dict, blank=True)),
                ("lease_token", models.UUIDField(null=True, blank=True)),
                ("lease_expires_at", models.DateTimeField(null=True, blank=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("error_code", models.CharField(max_length=40, blank=True, default="")),
                ("approved_at", models.DateTimeField(null=True, blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name="freelance_synthetic_jobs")),
            ],
            options={"indexes": [models.Index(fields=["state", "created_at"], name="ua_flj_state_created_idx")]},
        ),
    ]
