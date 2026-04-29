from datetime import timedelta

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def default_oauth_state_expiry():
    return timezone.now() + timedelta(minutes=15)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_growth", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GrowthAutomationRecipe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=180)),
                ("trigger_type", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("recipe", models.JSONField(blank=True, default=dict)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="GrowthChannelConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(choices=[("META", "Meta"), ("INSTAGRAM", "Instagram"), ("LINKEDIN", "LinkedIn"), ("X", "X"), ("YOUTUBE", "YouTube")], max_length=32)),
                ("account_label", models.CharField(blank=True, max_length=180)),
                ("external_account_id", models.CharField(blank=True, max_length=180)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("CONNECTED", "Connected"), ("ERROR", "Error"), ("DISCONNECTED", "Disconnected")], default="PENDING", max_length=20)),
                ("scopes", models.JSONField(blank=True, default=list)),
                ("connected_at", models.DateTimeField(blank=True, null=True)),
                ("disconnected_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["provider", "-created_at"]},
        ),
        migrations.CreateModel(
            name="GrowthContentDraft",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=180)),
                ("body", models.TextField(blank=True)),
                ("media_urls", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("READY", "Ready"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("ARCHIVED", "Archived")], default="DRAFT", max_length=20)),
                ("source", models.CharField(blank=True, max_length=40)),
                ("prompt", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="GrowthOAuthState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(max_length=32)),
                ("state", models.CharField(max_length=255, unique=True)),
                ("redirect_uri", models.URLField(blank=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("USED", "Used"), ("EXPIRED", "Expired"), ("CANCELED", "Canceled")], default="PENDING", max_length=20)),
                ("expires_at", models.DateTimeField(default=default_oauth_state_expiry)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="GrowthContentQueueItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("QUEUED", "Queued"), ("SCHEDULED", "Scheduled"), ("CANCELED", "Canceled"), ("FAILED", "Failed"), ("POSTED", "Posted")], default="QUEUED", max_length=20)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("fail_reason", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("channel_connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="queue_items", to="platform_growth.growthchannelconnection")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("draft", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="queue_items", to="platform_growth.growthcontentdraft")),
            ],
            options={"ordering": ["scheduled_for", "-created_at"]},
        ),
        migrations.CreateModel(
            name="GrowthOAuthToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(max_length=32)),
                ("token_type", models.CharField(blank=True, max_length=32)),
                ("access_token", models.TextField(blank=True)),
                ("refresh_token", models.TextField(blank=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("scope", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="oauth_tokens", to="platform_growth.growthchannelconnection")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="GrowthScheduledPostJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("run_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("READY", "Ready"), ("PAUSED", "Paused"), ("CANCELED", "Canceled"), ("COMPLETED", "Completed")], default="PENDING", max_length=20)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("queue_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scheduled_jobs", to="platform_growth.growthcontentqueueitem")),
            ],
            options={"ordering": ["run_at", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="growthchannelconnection",
            constraint=models.UniqueConstraint(fields=("provider", "external_account_id"), name="uniq_growth_provider_external_account"),
        ),
        migrations.AddIndex(model_name="growthoauthstate", index=models.Index(fields=["provider", "status"], name="platform_gro_provide_2664aa_idx")),
        migrations.AddIndex(model_name="growthoauthstate", index=models.Index(fields=["expires_at"], name="platform_gro_expires_0d53c0_idx")),
        migrations.AddIndex(model_name="growthcontentqueueitem", index=models.Index(fields=["status", "scheduled_for"], name="platform_gro_status_725f79_idx")),
        migrations.AddIndex(model_name="growthscheduledpostjob", index=models.Index(fields=["status", "run_at"], name="platform_gro_status_3a74f0_idx")),
    ]