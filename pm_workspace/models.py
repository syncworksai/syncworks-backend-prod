from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class PMWorkspace(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pm_workspaces")
    name = models.CharField(max_length=180)
    manager_name = models.CharField(max_length=180, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    office_email = models.EmailField(blank=True)
    tenant_email = models.EmailField(blank=True)
    reply_to_email = models.EmailField(blank=True)
    sender_name = models.CharField(max_length=180, blank=True)
    website = models.URLField(blank=True)
    office_address = models.CharField(max_length=255, blank=True)
    email_signature = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]


class PMProperty(models.Model):
    class PropertyType(models.TextChoices):
        HOME = "HOME", "Single-family home"
        MULTIFAMILY = "MULTIFAMILY", "Multifamily"
        APARTMENT = "APARTMENT", "Apartment building"
        CONDO = "CONDO", "Condominium"
        TOWNHOME = "TOWNHOME", "Townhome"
        COMMERCIAL = "COMMERCIAL", "Commercial"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        HEALTHY = "HEALTHY", "Healthy"
        WATCH = "WATCH", "Watch"
        AT_RISK = "AT_RISK", "At risk"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="properties")
    name = models.CharField(max_length=180)
    property_type = models.CharField(max_length=24, choices=PropertyType.choices, default=PropertyType.HOME)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    zip = models.CharField(max_length=12)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.HEALTHY)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_pm_properties",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["workspace", "status"])]


class PMTenant(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        INVITE_PENDING = "INVITE_PENDING", "Invite pending"
        CONNECTED = "CONNECTED", "Connected"
        INACTIVE = "INACTIVE", "Inactive"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="tenants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="pm_tenant_records")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    property_name = models.CharField(max_length=180, blank=True)
    unit_label = models.CharField(max_length=80, blank=True)
    move_in_date = models.DateField(null=True, blank=True)
    lease_start = models.DateField(null=True, blank=True)
    lease_end = models.DateField(null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_tenants")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "id"]
        constraints = [models.UniqueConstraint(fields=["workspace", "email"], name="uniq_pm_workspace_tenant_email")]


class PMTenantInvitation(models.Model):
    class Mode(models.TextChoices):
        COMPLETE_RECORD = "COMPLETE_RECORD", "PM completed tenant record"
        TENANT_ONBOARDING = "TENANT_ONBOARDING", "Tenant completes onboarding"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        REVOKED = "REVOKED", "Revoked"
        EXPIRED = "EXPIRED", "Expired"

    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="invitations")
    mode = models.CharField(max_length=24, choices=Mode.choices, default=Mode.COMPLETE_RECORD)
    code = models.CharField(max_length=32, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    sent_to_email = models.EmailField()
    sent_from_name = models.CharField(max_length=180, blank=True)
    reply_to_email = models.EmailField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"SW-TN-{secrets.token_hex(4).upper()}"
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
