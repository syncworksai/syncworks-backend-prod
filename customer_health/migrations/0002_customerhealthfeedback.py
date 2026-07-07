# Generated manually for Health beta feedback intake.

from __future__ import annotations

import django.db.models.deletion
import customer_health.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customer_health", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerHealthFeedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "client_feedback_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=128,
                    ),
                ),
                (
                    "area",
                    models.CharField(
                        blank=True,
                        default="General",
                        max_length=64,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("Low", "Low"),
                            ("Medium", "Medium"),
                            ("High", "High"),
                            ("Blocking", "Blocking"),
                        ],
                        default="Medium",
                        max_length=32,
                    ),
                ),
                ("message", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("OPEN", "Open"),
                            ("REVIEWED", "Reviewed"),
                            ("CLOSED", "Closed"),
                        ],
                        db_index=True,
                        default="OPEN",
                        max_length=32,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        blank=True,
                        default="health_web_beta",
                        max_length=64,
                    ),
                ),
                (
                    "page_path",
                    models.CharField(
                        blank=True,
                        max_length=500,
                    ),
                ),
                (
                    "runtime_json",
                    models.JSONField(
                        blank=True,
                        default=customer_health.models.default_dict,
                    ),
                ),
                (
                    "extra_json",
                    models.JSONField(
                        blank=True,
                        default=customer_health.models.default_dict,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="customer_health_feedback",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Customer Health Feedback",
                "verbose_name_plural": "Customer Health Feedback",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="customerhealthfeedback",
            index=models.Index(
                fields=["status", "-created_at"],
                name="customer_he_status_7dc96b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="customerhealthfeedback",
            index=models.Index(
                fields=["severity", "-created_at"],
                name="customer_he_severit_15ce3d_idx",
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="profile_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_dict,
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="snapshot_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_dict,
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="workouts_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_list,
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="history_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_list,
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="progress_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_list,
            ),
        ),
        migrations.AlterField(
            model_name="customerhealthprofile",
            name="devices_json",
            field=models.JSONField(
                blank=True,
                default=customer_health.models.default_list,
            ),
        ),
    ]