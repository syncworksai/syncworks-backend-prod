from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .businesses import Business


class ServiceCategory(models.Model):
    key = models.CharField(max_length=60, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return self.name


class BusinessCategory(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="business_categories")
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name="category_businesses")

    class Meta:
        unique_together = ("business", "category")

    def __str__(self) -> str:
        return f"{self.business_id}:{self.category_id}"


class ServiceRequest(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="service_requests")
    category = models.ForeignKey(ServiceCategory, on_delete=models.PROTECT, related_name="service_requests")

    title = models.CharField(max_length=140)
    description = models.TextField(blank=True, default="")

    # added in your 0002 migration
    preferred_sbo_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="preferred_requests",
    )

    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"SR#{self.id} {self.title}"
