from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0005_pmworkorder"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMPropertyOwner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("owner_type", models.CharField(choices=[("COMPANY", "Management company"), ("INDIVIDUAL", "Individual investor"), ("ENTITY", "Ownership entity")], default="INDIVIDUAL", max_length=20)),
                ("name", models.CharField(max_length=180)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("mailing_address", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("portal_invited", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_property_owners", to=settings.AUTH_USER_MODEL)),
                ("properties", models.ManyToManyField(blank=True, related_name="ownership_records", to="pm_workspace.pmproperty")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="property_owners", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.AddConstraint(
            model_name="pmpropertyowner",
            constraint=models.UniqueConstraint(fields=("workspace", "name"), name="uniq_pm_workspace_owner_name"),
        ),
    ]
