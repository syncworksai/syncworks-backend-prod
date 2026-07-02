import django.db.models.deletion
import django.utils.timezone
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0110_business_customer_crm"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessDataImport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "import_type",
                    models.CharField(
                        choices=[
                            ("CUSTOMERS", "Customers"),
                            ("TICKETS", "Tickets"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PREVIEWED", "Previewed"),
                            ("READY", "Ready"),
                            ("COMPLETED", "Completed"),
                            (
                                "COMPLETED_WITH_ERRORS",
                                "Completed with errors",
                            ),
                            ("FAILED", "Failed"),
                        ],
                        db_index=True,
                        default="PREVIEWED",
                        max_length=30,
                    ),
                ),
                (
                    "source_system",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "original_filename",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("file_size_bytes", models.PositiveIntegerField(default=0)),
                ("column_mapping", models.JSONField(blank=True, default=dict)),
                ("headers", models.JSONField(blank=True, default=list)),
                ("sample_rows", models.JSONField(blank=True, default=list)),
                ("total_rows", models.PositiveIntegerField(default=0)),
                ("valid_rows", models.PositiveIntegerField(default=0)),
                ("skipped_rows", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("errors", models.JSONField(blank=True, default=list)),
                ("summary", models.JSONField(blank=True, default=dict)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="data_imports",
                        to="user_accounts.business",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="business_data_imports_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="businessdataimport",
            index=models.Index(
                fields=["business", "import_type", "created_at"],
                name="ua_import_biz_type_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="businessdataimport",
            index=models.Index(
                fields=["business", "status", "created_at"],
                name="ua_import_biz_status_idx",
            ),
        ),
    ]
