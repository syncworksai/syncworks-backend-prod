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
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_properties")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["workspace", "status"])]


class PMProject(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        PLANNING = "PLANNING", "Planning"
        APPROVAL = "APPROVAL", "Quotes and approvals"
        SCHEDULED = "SCHEDULED", "Scheduled"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        REVIEW = "REVIEW", "Inspection or review"
        COMPLETED = "COMPLETED", "Completed"
        ARCHIVED = "ARCHIVED", "Archived"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class AssignmentType(models.TextChoices):
        INTERNAL = "INTERNAL", "Internal"
        EXTERNAL = "EXTERNAL", "External"
        UNASSIGNED = "UNASSIGNED", "Unassigned"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="projects")
    property = models.ForeignKey(PMProperty, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    unit_label = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    assignment_type = models.CharField(max_length=16, choices=AssignmentType.choices, default=AssignmentType.UNASSIGNED)
    internal_assignee_name = models.CharField(max_length=180, blank=True)
    internal_assignee_email = models.EmailField(blank=True)
    external_assignee_name = models.CharField(max_length=180, blank=True)
    external_assignee_email = models.EmailField(blank=True)
    vendor_title = models.CharField(max_length=180, blank=True)
    vendor_contact_name = models.CharField(max_length=180, blank=True)
    vendor_email = models.EmailField(blank=True)
    contract_reference = models.CharField(max_length=180, blank=True)
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    blocker = models.TextField(blank=True)
    next_action = models.TextField(blank=True)
    next_action_due = models.DateField(null=True, blank=True)
    update_recipient_emails = models.TextField(blank=True)
    custom_data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_projects")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["workspace", "status"]), models.Index(fields=["workspace", "target_date"])]


class PMProjectUpdate(models.Model):
    project = models.ForeignKey(PMProject, on_delete=models.CASCADE, related_name="updates")
    note = models.TextField()
    status = models.CharField(max_length=24, choices=PMProject.Status.choices, blank=True)
    progress_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    blocker = models.TextField(blank=True)
    next_action = models.TextField(blank=True)
    next_action_due = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="pm_project_updates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


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


class PMUnit(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        OCCUPIED = "OCCUPIED", "Occupied"
        NOTICE_GIVEN = "NOTICE_GIVEN", "Notice given"
        MAKE_READY = "MAKE_READY", "Make ready"
        CONSTRUCTION = "CONSTRUCTION", "Under construction"
        OFF_MARKET = "OFF_MARKET", "Off market"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="units")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="units")
    label = models.CharField(max_length=80)
    bedrooms = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bathrooms = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    square_feet = models.PositiveIntegerField(null=True, blank=True)
    market_rent = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    availability = models.CharField(max_length=24, choices=Availability.choices, default=Availability.AVAILABLE)
    available_date = models.DateField(null=True, blank=True)
    accepts_section8 = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property__name", "label"]
        constraints = [models.UniqueConstraint(fields=["property", "label"], name="uniq_pm_property_unit_label")]


class PMProspect(models.Model):
    class Stage(models.TextChoices):
        LEAD = "LEAD", "Lead"
        APPLICATION_SENT = "APPLICATION_SENT", "Application sent"
        APPLICATION_RECEIVED = "APPLICATION_RECEIVED", "Application received"
        SCREENING = "SCREENING", "Screening"
        APPROVED = "APPROVED", "Approved"
        SHOWING_SCHEDULED = "SHOWING_SCHEDULED", "Showing scheduled"
        READY_FOR_ONBOARDING = "READY_FOR_ONBOARDING", "Ready for onboarding"
        CONVERTED = "CONVERTED", "Converted to tenant"
        DECLINED = "DECLINED", "Declined"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="prospects")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    stage = models.CharField(max_length=32, choices=Stage.choices, default=Stage.LEAD)
    section8_requested = models.BooleanField(default=False)
    voucher_authority = models.CharField(max_length=180, blank=True)
    voucher_bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    desired_move_in = models.DateField(null=True, blank=True)
    desired_bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    max_rent = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    assigned_unit = models.ForeignKey(PMUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="prospects")
    showing_at = models.DateTimeField(null=True, blank=True)
    application_sent_at = models.DateTimeField(null=True, blank=True)
    application_received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_prospects")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["workspace", "stage"])]


class PMLease(models.Model):
    class Term(models.TextChoices):
        MONTH_TO_MONTH = "MONTH_TO_MONTH", "Month to month"
        SIX_MONTH = "SIX_MONTH", "6 month"
        TWELVE_MONTH = "TWELVE_MONTH", "12 month"
        CUSTOM = "CUSTOM", "Custom"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="leases")
    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="leases")
    unit = models.ForeignKey(PMUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="leases")
    term = models.CharField(max_length=24, choices=Term.choices, default=Term.TWELVE_MONTH)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    converts_to_month_to_month = models.BooleanField(default=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    section8 = models.BooleanField(default=False)
    housing_authority = models.CharField(max_length=180, blank=True)
    tenant_portion = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    assistance_portion = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=24, default="DRAFT")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-id"]


class PMDocumentPacket(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PARTIALLY_SIGNED = "PARTIALLY_SIGNED", "Partially signed"
        COMPLETED = "COMPLETED", "Completed"
        VOID = "VOID", "Void"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="document_packets")
    tenant = models.ForeignKey(PMTenant, null=True, blank=True, on_delete=models.CASCADE, related_name="document_packets")
    prospect = models.ForeignKey(PMProspect, null=True, blank=True, on_delete=models.CASCADE, related_name="document_packets")
    lease = models.ForeignKey(PMLease, null=True, blank=True, on_delete=models.SET_NULL, related_name="document_packets")
    packet_type = models.CharField(max_length=80, default="LEASE")
    state_code = models.CharField(max_length=2, blank=True)
    housing_authority = models.CharField(max_length=180, blank=True)
    template_name = models.CharField(max_length=180)
    template_version = models.CharField(max_length=80, blank=True)
    source_url = models.URLField(blank=True)
    field_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]


class PMLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CHARGE = "CHARGE", "Charge"
        PAYMENT = "PAYMENT", "Payment"
        CREDIT = "CREDIT", "Credit"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        ACH = "ACH", "ACH"
        CARD = "CARD", "Card"
        MONEY_ORDER = "MONEY_ORDER", "Money order"
        HOUSING_AUTHORITY = "HOUSING_AUTHORITY", "Housing authority"
        OTHER = "OTHER", "Other"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="ledger_entries")
    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="ledger_entries")
    lease = models.ForeignKey(PMLease, null=True, blank=True, on_delete=models.SET_NULL, related_name="ledger_entries")
    entry_date = models.DateField(default=timezone.localdate)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=80, default="RENT")
    payment_method = models.CharField(max_length=24, choices=Method.choices, blank=True)
    reference = models.CharField(max_length=180, blank=True)
    memo = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_ledger_entries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_date", "-id"]
        indexes = [models.Index(fields=["workspace", "tenant", "entry_date"])]
