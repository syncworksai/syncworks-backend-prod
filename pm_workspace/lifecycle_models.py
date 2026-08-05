from django.conf import settings
from django.db import models

from .models import PMLease, PMProperty, PMTenant, PMUnit, PMWorkspace


class PMOccupancy(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending move-in"
        ACTIVE = "ACTIVE", "Active"
        NOTICE_GIVEN = "NOTICE_GIVEN", "Notice given"
        MOVED_OUT = "MOVED_OUT", "Moved out"
        EVICTED = "EVICTED", "Evicted"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="occupancies")
    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="occupancies")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="occupancies")
    unit = models.ForeignKey(PMUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="occupancies")
    lease = models.ForeignKey(PMLease, null=True, blank=True, on_delete=models.SET_NULL, related_name="occupancies")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    move_in_date = models.DateField(null=True, blank=True)
    notice_date = models.DateField(null=True, blank=True)
    move_out_date = models.DateField(null=True, blank=True)
    move_out_reason = models.CharField(max_length=180, blank=True)
    forwarding_address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_occupancies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-move_in_date", "-id"]
        indexes = [
            models.Index(fields=["workspace", "property", "status"]),
            models.Index(fields=["workspace", "tenant", "status"]),
        ]


class PMTenantCase(models.Model):
    class CaseType(models.TextChoices):
        EVICTION = "EVICTION", "Eviction"
        COLLECTIONS = "COLLECTIONS", "Collections"
        LEGAL = "LEGAL", "Legal"
        PAYMENT_PLAN = "PAYMENT_PLAN", "Payment plan"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        NOTICE_SENT = "NOTICE_SENT", "Notice sent"
        FILED = "FILED", "Filed"
        JUDGMENT = "JUDGMENT", "Judgment"
        SENT_TO_COLLECTIONS = "SENT_TO_COLLECTIONS", "Sent to collections"
        PAYMENT_PLAN = "PAYMENT_PLAN", "Payment plan"
        CLOSED = "CLOSED", "Closed"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="tenant_cases")
    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="cases")
    property = models.ForeignKey(PMProperty, null=True, blank=True, on_delete=models.SET_NULL, related_name="tenant_cases")
    occupancy = models.ForeignKey(PMOccupancy, null=True, blank=True, on_delete=models.SET_NULL, related_name="cases")
    case_type = models.CharField(max_length=24, choices=CaseType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    opened_date = models.DateField()
    filed_date = models.DateField(null=True, blank=True)
    judgment_date = models.DateField(null=True, blank=True)
    collections_sent_date = models.DateField(null=True, blank=True)
    agency_name = models.CharField(max_length=180, blank=True)
    agency_email = models.EmailField(blank=True)
    balance_at_open = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reference = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_tenant_cases")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-opened_date", "-id"]
        indexes = [models.Index(fields=["workspace", "status"]), models.Index(fields=["workspace", "tenant"])]
