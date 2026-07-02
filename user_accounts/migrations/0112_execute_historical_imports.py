import django.db.models.deletion

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0111_business_data_import_preview"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessdataimport",
            name="imported_rows",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="businessdataimport",
            name="matched_rows",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="businessdataimport",
            name="payload_rows",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="businessdataimport",
            name="status",
            field=models.CharField(
                choices=[
                    ("PREVIEWED", "Previewed"),
                    ("READY", "Ready"),
                    ("PROCESSING", "Processing"),
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
        migrations.AddField(
            model_name="ticket",
            name="business_customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets",
                to="user_accounts.businesscustomer",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="exclude_from_operational_kpis",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="ticket",
            name="external_ticket_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=160,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="import_batch_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="is_imported",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="ticket",
            name="original_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="source_system",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=100,
            ),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(
                fields=["assigned_business", "is_imported", "created_at"],
                name="ua_ticket_imported_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(
                fields=[
                    "assigned_business",
                    "source_system",
                    "external_ticket_id",
                ],
                name="ua_ticket_external_idx",
            ),
        ),
    ]
