# Generated manually for customer_health initial profile sync.

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def default_dict():
    return {}


def default_list():
    return []


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerHealthProfile",
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
                    "profile_json",
                    models.JSONField(
                        blank=True,
                        default=default_dict,
                    ),
                ),
                (
                    "snapshot_json",
                    models.JSONField(
                        blank=True,
                        default=default_dict,
                    ),
                ),
                (
                    "workouts_json",
                    models.JSONField(
                        blank=True,
                        default=default_list,
                    ),
                ),
                (
                    "history_json",
                    models.JSONField(
                        blank=True,
                        default=default_list,
                    ),
                ),
                (
                    "progress_json",
                    models.JSONField(
                        blank=True,
                        default=default_list,
                    ),
                ),
                (
                    "devices_json",
                    models.JSONField(
                        blank=True,
                        default=default_list,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
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
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="customer_health_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Customer Health Profile",
                "verbose_name_plural": "Customer Health Profiles",
                "ordering": ["-updated_at"],
            },
        ),
    ]