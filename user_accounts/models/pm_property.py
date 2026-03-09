# backend/user_accounts/models/pm_property.py
from __future__ import annotations

from django.db import models

from user_accounts.models.business import Business


class PMProperty(models.Model):
    class Status(models.TextChoices):
        HEALTHY = "HEALTHY", "Healthy"
        WATCH = "WATCH", "Watch"
        AT_RISK = "AT_RISK", "At Risk"

    class PropertyType(models.TextChoices):
        HOME = "HOME", "Home / Single Family"
        APARTMENT = "APARTMENT", "Apartment Building"
        MULTI_FAMILY = "MULTI_FAMILY", "Multi-Family (2–4)"
        CONDO = "CONDO", "Condo"
        COMMERCIAL = "COMMERCIAL", "Commercial"
        OTHER = "OTHER", "Other"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_properties")

    name = models.CharField(max_length=200)

    # ✅ NEW: property type (Home vs Apartment, etc.)
    property_type = models.CharField(
        max_length=20,
        choices=PropertyType.choices,
        default=PropertyType.HOME,
    )

    address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    state = models.CharField(max_length=2, blank=True, default="")
    zip = models.CharField(max_length=10, blank=True, default="")

    notes = models.TextField(blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.HEALTHY)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "created_at"]),
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "name"]),
            models.Index(fields=["business", "property_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (biz={self.business_id})"
