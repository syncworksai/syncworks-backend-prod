from django.conf import settings
from django.db import models

from .models import PMProperty, PMWorkspace


class PMPropertyOwner(models.Model):
    class OwnerType(models.TextChoices):
        COMPANY = "COMPANY", "Management company"
        INDIVIDUAL = "INDIVIDUAL", "Individual investor"
        ENTITY = "ENTITY", "Ownership entity"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="property_owners")
    owner_type = models.CharField(max_length=20, choices=OwnerType.choices, default=OwnerType.INDIVIDUAL)
    name = models.CharField(max_length=180)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    mailing_address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    portal_invited = models.BooleanField(default=False)
    properties = models.ManyToManyField(PMProperty, related_name="ownership_records", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_property_owners")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="uniq_pm_workspace_owner_name")]
