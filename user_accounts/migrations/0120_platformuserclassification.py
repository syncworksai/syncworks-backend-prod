from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0119_controlled_kpi_invoice_state_sync"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformUserClassification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("UNCLASSIFIED", "Unclassified"), ("REAL_USER", "Real user"), ("TEST_ACCOUNT", "Test account"), ("BETA_TESTER", "Beta tester"), ("INTERNAL", "Internal"), ("DEMO", "Demo"), ("BILLING_RESTRICTED", "Billing restricted"), ("SUSPENDED", "Suspended")], db_index=True, default="UNCLASSIFIED", max_length=32)),
                ("note", models.TextField(blank=True)),
                ("classified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("classified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_user_classifications_made", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="platform_classification", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["user_id"]},
        ),
    ]
