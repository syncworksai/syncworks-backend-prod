from __future__ import annotations

from django.db import models

from user_accounts.models.business import Business
from user_accounts.models.pm_property import PMProperty
from user_accounts.models.pm_unit import PMUnit


class PMTenant(models.Model):
    class Status(models.TextChoices):
        PROSPECT = "PROSPECT", "Prospect"
        APPLICANT = "APPLICANT", "Applicant"
        TENANT = "TENANT", "Tenant"
        FORMER = "FORMER", "Former"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_tenants")

    property = models.ForeignKey(
        PMProperty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
    )

    unit = models.ForeignKey(
        PMUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
    )

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, blank=True, default="")

    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROSPECT)

    section8 = models.BooleanField(default=False)
    voucher_id = models.CharField(max_length=64, blank=True, default="")

    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "email"]),
            models.Index(fields=["business", "phone"]),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() + f" (biz={self.business_id})"
