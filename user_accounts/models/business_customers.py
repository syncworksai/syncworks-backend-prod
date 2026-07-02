from __future__ import annotations

import re

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


def normalize_phone(value: str) -> str:
    return re.sub(r"\D+", "", str(value or ""))[-15:]


class BusinessCustomer(models.Model):
    class RecordSource(models.TextChoices):
        SYNCWORKS = "SYNCWORKS", "SyncWorks"
        MANUAL = "MANUAL", "Manual"
        IMPORTED = "IMPORTED", "Imported"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="business_customers",
    )

    name = models.CharField(max_length=200, blank=True, default="")
    company_name = models.CharField(max_length=200, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    normalized_phone = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
    )

    billing_address = models.CharField(max_length=255, blank=True, default="")
    service_address = models.CharField(max_length=255, blank=True, default="")
    unit = models.CharField(max_length=80, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    state = models.CharField(max_length=40, blank=True, default="")
    service_zip = models.CharField(max_length=20, blank=True, default="")
    access_notes = models.TextField(blank=True, default="")

    contact_preference = models.CharField(
        max_length=30,
        blank=True,
        default="either",
    )
    payment_preference = models.CharField(
        max_length=30,
        blank=True,
        default="quote_first",
    )
    notes = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)

    record_source = models.CharField(
        max_length=20,
        choices=RecordSource.choices,
        default=RecordSource.SYNCWORKS,
        db_index=True,
    )
    source_system = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )
    external_customer_id = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
    )
    is_imported = models.BooleanField(default=False, db_index=True)
    import_batch_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )
    exclude_from_kpis = models.BooleanField(default=False, db_index=True)

    first_service_at = models.DateTimeField(null=True, blank=True)
    last_service_at = models.DateTimeField(null=True, blank=True)
    ticket_count = models.PositiveIntegerField(default=0)
    completed_ticket_count = models.PositiveIntegerField(default=0)
    cancelled_ticket_count = models.PositiveIntegerField(default=0)
    lifetime_revenue_cents = models.PositiveBigIntegerField(default=0)

    last_service_label = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )
    last_ticket = models.ForeignKey(
        "user_accounts.Ticket",
        on_delete=models.SET_NULL,
        related_name="last_customer_profiles",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="business_customers_created",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="business_customers_updated",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(
                fields=["business", "name"],
                name="ua_bc_business_name_idx",
            ),
            models.Index(
                fields=["business", "email"],
                name="ua_bc_business_email_idx",
            ),
            models.Index(
                fields=["business", "normalized_phone"],
                name="ua_bc_business_phone_idx",
            ),
            models.Index(
                fields=[
                    "business",
                    "source_system",
                    "external_customer_id",
                ],
                name="ua_bc_external_idx",
            ),
            models.Index(
                fields=["business", "is_imported", "updated_at"],
                name="ua_bc_imported_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = str(self.email or "").strip().lower()
        self.phone = str(self.phone or "").strip()
        self.normalized_phone = normalize_phone(self.phone)
        self.name = str(self.name or "").strip()
        self.company_name = str(self.company_name or "").strip()
        self.state = str(self.state or "").strip().upper()
        self.service_zip = str(self.service_zip or "").strip()
        self.source_system = str(self.source_system or "").strip()
        self.external_customer_id = str(
            self.external_customer_id or ""
        ).strip()

        if self.record_source == self.RecordSource.IMPORTED:
            self.is_imported = True

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = (
            self.name
            or self.company_name
            or self.email
            or self.phone
            or f"Customer {self.id}"
        )
        return f"{self.business_id}: {label}"
