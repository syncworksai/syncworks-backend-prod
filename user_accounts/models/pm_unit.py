from __future__ import annotations

from django.db import models

from user_accounts.models.business import Business
from user_accounts.models.pm_property import PMProperty


class PMUnit(models.Model):
    class Status(models.TextChoices):
        VACANT = "VACANT", "Vacant"
        OCCUPIED = "OCCUPIED", "Occupied"
        MAINTENANCE = "MAINTENANCE", "Maintenance / Rehab"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_units")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="units")

    label = models.CharField(max_length=60, help_text="Unit label like 101, A, 2B")

    beds = models.PositiveSmallIntegerField(default=0)
    baths = models.DecimalField(max_digits=3, decimal_places=1, default=0.0)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.VACANT)

    section8_eligible = models.BooleanField(default=False)
    section8_active = models.BooleanField(default=False)

    market_rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property_id", "label"]
        indexes = [
            models.Index(fields=["business", "property"]),
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "label"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} (property={self.property_id}, biz={self.business_id})"
