from django.conf import settings
from django.db import models

from .models import PMProperty, PMTenant, PMUnit, PMWorkspace


class PMWorkOrder(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        TRIAGE = "TRIAGE", "Triage"
        ASSIGNED = "ASSIGNED", "Assigned"
        MARKETPLACE = "MARKETPLACE", "Marketplace"
        SCHEDULED = "SCHEDULED", "Scheduled"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        WAITING_PARTS = "WAITING_PARTS", "Waiting on parts"
        WAITING_APPROVAL = "WAITING_APPROVAL", "Waiting approval"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        ROUTINE = "ROUTINE", "Routine"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"
        EMERGENCY = "EMERGENCY", "Emergency"

    class Source(models.TextChoices):
        CALL_IN = "CALL_IN", "Call-in request"
        OFFICE = "OFFICE", "Office entered"
        TENANT_PORTAL = "TENANT_PORTAL", "Tenant portal"
        INSPECTION = "INSPECTION", "Inspection"
        PREVENTIVE = "PREVENTIVE", "Preventive maintenance"

    class Dispatch(models.TextChoices):
        UNASSIGNED = "UNASSIGNED", "Unassigned"
        INTERNAL = "INTERNAL", "Internal team"
        VENDOR = "VENDOR", "Known vendor"
        MARKETPLACE = "MARKETPLACE", "SyncWorks marketplace"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="work_orders")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="work_orders")
    unit = models.ForeignKey(PMUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="work_orders")
    tenant = models.ForeignKey(PMTenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="work_orders")
    source = models.CharField(max_length=24, choices=Source.choices, default=Source.CALL_IN)
    category = models.CharField(max_length=40)
    issue_type = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField()
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.ROUTINE)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEW)
    dispatch_mode = models.CharField(max_length=24, choices=Dispatch.choices, default=Dispatch.UNASSIGNED)
    caller_name = models.CharField(max_length=180, blank=True)
    caller_phone = models.CharField(max_length=40, blank=True)
    permission_to_enter = models.BooleanField(default=False)
    pets_or_access_notes = models.TextField(blank=True)
    preferred_schedule = models.CharField(max_length=180, blank=True)
    water_shutoff = models.BooleanField(default=False)
    electrical_hazard = models.BooleanField(default=False)
    active_leak = models.BooleanField(default=False)
    no_heat_or_air = models.BooleanField(default=False)
    appliance_make_model = models.CharField(max_length=180, blank=True)
    internal_assignee = models.CharField(max_length=180, blank=True)
    vendor_name = models.CharField(max_length=180, blank=True)
    vendor_email = models.EmailField(blank=True)
    vendor_phone = models.CharField(max_length=40, blank=True)
    not_to_exceed = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    marketplace_ticket_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    marketplace_requested_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_hub_work_orders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["workspace", "property", "status"]),
            models.Index(fields=["workspace", "priority"]),
        ]
