import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMProperty",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("property_type", models.CharField(choices=[("HOME", "Single-family home"), ("MULTIFAMILY", "Multifamily"), ("APARTMENT", "Apartment building"), ("CONDO", "Condominium"), ("TOWNHOME", "Townhome"), ("COMMERCIAL", "Commercial"), ("OTHER", "Other")], default="HOME", max_length=24)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(max_length=120)),
                ("state", models.CharField(max_length=2)),
                ("zip", models.CharField(max_length=12)),
                ("status", models.CharField(choices=[("HEALTHY", "Healthy"), ("WATCH", "Watch"), ("AT_RISK", "At risk")], default="HEALTHY", max_length=16)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_properties", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="properties", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.AddIndex(
            model_name="pmproperty",
            index=models.Index(fields=["workspace", "status"], name="pm_workspac_workspa_7cf4bb_idx"),
        ),
    ]
