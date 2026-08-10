from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0009_pmoccupancy_pmtenantcase_conversation_links"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMPropertyProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bedrooms", models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ("bathrooms", models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ("square_feet", models.PositiveIntegerField(blank=True, null=True)),
                ("year_built", models.PositiveIntegerField(blank=True, null=True)),
                ("furnished", models.BooleanField(default=False)),
                ("utility_electric", models.CharField(blank=True, max_length=180)),
                ("utility_gas", models.CharField(blank=True, max_length=180)),
                ("utility_water", models.CharField(blank=True, max_length=180)),
                ("utility_trash", models.CharField(blank=True, max_length=180)),
                ("sewer_septic", models.CharField(blank=True, max_length=180)),
                ("hvac_details", models.TextField(blank=True)),
                ("roof_details", models.TextField(blank=True)),
                ("water_heater_details", models.TextField(blank=True)),
                ("access_details", models.TextField(blank=True)),
                ("insurance_details", models.TextField(blank=True)),
                ("warranty_notes", models.TextField(blank=True)),
                ("parking_details", models.TextField(blank=True)),
                ("safety_details", models.TextField(blank=True)),
                ("general_notes", models.TextField(blank=True)),
                ("custom_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("property", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="detail_profile", to="pm_workspace.pmproperty")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_pm_property_profiles", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="property_detail_profiles", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["property__name", "property_id"]},
        ),
        migrations.CreateModel(
            name="PMPropertyAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("FURNITURE", "Furniture"), ("APPLIANCE", "Appliance"), ("HVAC", "HVAC"), ("PLUMBING", "Plumbing"), ("ELECTRICAL", "Electrical"), ("ACCESS", "Keys / access"), ("UTILITY", "Utility / service"), ("SAFETY", "Safety equipment"), ("FIXTURE", "Fixture"), ("AMENITY", "Amenity"), ("WARRANTY", "Warranty / service plan"), ("OTHER", "Other")], default="OTHER", max_length=24)),
                ("name", models.CharField(max_length=180)),
                ("room_location", models.CharField(blank=True, max_length=120)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("condition", models.CharField(choices=[("NEW", "New"), ("EXCELLENT", "Excellent"), ("GOOD", "Good"), ("FAIR", "Fair"), ("POOR", "Poor"), ("NEEDS_REPAIR", "Needs repair"), ("MISSING", "Missing")], default="GOOD", max_length=24)),
                ("furnished_item", models.BooleanField(default=False)),
                ("brand", models.CharField(blank=True, max_length=120)),
                ("model_number", models.CharField(blank=True, max_length=120)),
                ("serial_number", models.CharField(blank=True, max_length=160)),
                ("provider_name", models.CharField(blank=True, max_length=180)),
                ("account_reference", models.CharField(blank=True, max_length=180)),
                ("purchase_date", models.DateField(blank=True, null=True)),
                ("warranty_expiration", models.DateField(blank=True, null=True)),
                ("replacement_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_property_assets", to=settings.AUTH_USER_MODEL)),
                ("photo_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inventory_items", to="pm_workspace.pmpropertydocument")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_items", to="pm_workspace.pmproperty")),
                ("unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inventory_items", to="pm_workspace.pmunit")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="property_assets", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["room_location", "category", "name", "id"]},
        ),
        migrations.AddIndex(model_name="pmpropertyasset", index=models.Index(fields=["workspace", "property", "category"], name="pm_workspac_workspa_profcat_idx")),
        migrations.AddIndex(model_name="pmpropertyasset", index=models.Index(fields=["workspace", "property", "furnished_item"], name="pm_workspac_workspa_furnish_idx")),
    ]
