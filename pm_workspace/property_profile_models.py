from django.conf import settings
from django.db import models


class PMPropertyProfile(models.Model):
    property = models.OneToOneField("pm_workspace.PMProperty", on_delete=models.CASCADE, related_name="detail_profile")
    workspace = models.ForeignKey("pm_workspace.PMWorkspace", on_delete=models.CASCADE, related_name="property_detail_profiles")
    bedrooms = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bathrooms = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    square_feet = models.PositiveIntegerField(null=True, blank=True)
    year_built = models.PositiveIntegerField(null=True, blank=True)
    furnished = models.BooleanField(default=False)
    utility_electric = models.CharField(max_length=180, blank=True)
    utility_gas = models.CharField(max_length=180, blank=True)
    utility_water = models.CharField(max_length=180, blank=True)
    utility_trash = models.CharField(max_length=180, blank=True)
    sewer_septic = models.CharField(max_length=180, blank=True)
    hvac_details = models.TextField(blank=True)
    roof_details = models.TextField(blank=True)
    water_heater_details = models.TextField(blank=True)
    access_details = models.TextField(blank=True)
    insurance_details = models.TextField(blank=True)
    warranty_notes = models.TextField(blank=True)
    parking_details = models.TextField(blank=True)
    safety_details = models.TextField(blank=True)
    general_notes = models.TextField(blank=True)
    custom_data = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_pm_property_profiles")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property__name", "property_id"]


class PMPropertyAsset(models.Model):
    class Category(models.TextChoices):
        FURNITURE = "FURNITURE", "Furniture"
        APPLIANCE = "APPLIANCE", "Appliance"
        HVAC = "HVAC", "HVAC"
        PLUMBING = "PLUMBING", "Plumbing"
        ELECTRICAL = "ELECTRICAL", "Electrical"
        ACCESS = "ACCESS", "Keys / access"
        UTILITY = "UTILITY", "Utility / service"
        SAFETY = "SAFETY", "Safety equipment"
        FIXTURE = "FIXTURE", "Fixture"
        AMENITY = "AMENITY", "Amenity"
        WARRANTY = "WARRANTY", "Warranty / service plan"
        OTHER = "OTHER", "Other"

    class Condition(models.TextChoices):
        NEW = "NEW", "New"
        EXCELLENT = "EXCELLENT", "Excellent"
        GOOD = "GOOD", "Good"
        FAIR = "FAIR", "Fair"
        POOR = "POOR", "Poor"
        NEEDS_REPAIR = "NEEDS_REPAIR", "Needs repair"
        MISSING = "MISSING", "Missing"

    workspace = models.ForeignKey("pm_workspace.PMWorkspace", on_delete=models.CASCADE, related_name="property_assets")
    property = models.ForeignKey("pm_workspace.PMProperty", on_delete=models.CASCADE, related_name="inventory_items")
    unit = models.ForeignKey("pm_workspace.PMUnit", null=True, blank=True, on_delete=models.SET_NULL, related_name="inventory_items")
    category = models.CharField(max_length=24, choices=Category.choices, default=Category.OTHER)
    name = models.CharField(max_length=180)
    room_location = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    condition = models.CharField(max_length=24, choices=Condition.choices, default=Condition.GOOD)
    furnished_item = models.BooleanField(default=False)
    brand = models.CharField(max_length=120, blank=True)
    model_number = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=160, blank=True)
    provider_name = models.CharField(max_length=180, blank=True)
    account_reference = models.CharField(max_length=180, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    warranty_expiration = models.DateField(null=True, blank=True)
    replacement_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    photo_document = models.ForeignKey("pm_workspace.PMPropertyDocument", null=True, blank=True, on_delete=models.SET_NULL, related_name="inventory_items")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_property_assets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["room_location", "category", "name", "id"]
        indexes = [
            models.Index(fields=["workspace", "property", "category"]),
            models.Index(fields=["workspace", "property", "furnished_item"]),
        ]
