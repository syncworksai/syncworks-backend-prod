from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="PMCollectionSetup",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("business_id", models.PositiveIntegerField(db_index=True, unique=True)),
                ("method", models.CharField(choices=[
                    ("UNCONFIGURED", "Not configured"),
                    ("STRIPE_CONNECT", "Connect bank for SyncWorks payments"),
                    ("EXTERNAL", "Existing payment processor"),
                    ("MANUAL", "Cash/check/manual tracking")
                ], default="UNCONFIGURED", max_length=20)),
                ("external_provider_name", models.CharField(blank=True, default="", max_length=100)),
                ("external_provider_url", models.URLField(blank=True, default="", max_length=500)),
                ("trust_account_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("trust_account_reviewed_by_id", models.PositiveIntegerField(blank=True, null=True)),
                ("updated_by_id", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
