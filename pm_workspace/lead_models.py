import builtins

from django.conf import settings
from django.db import models

from .models import PMProperty, PMWorkspace


class PMLead(models.Model):
    class Stage(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        QUALIFIED = "QUALIFIED", "Qualified"
        REVIEWING = "REVIEWING", "Showing / reviewing"
        APPLICATION = "APPLICATION", "Application"
        APPROVED = "APPROVED", "Approved"
        LEASE_PENDING = "LEASE_PENDING", "Lease pending"
        WON = "WON", "Won"
        LOST = "LOST", "Lost"

    class LeadType(models.TextChoices):
        REGULAR = "REGULAR", "Regular tenant"
        CORPORATE = "CORPORATE", "Corporate leasing"
        INSURANCE = "INSURANCE", "Insurance housing"
        SECTION8 = "SECTION8", "Section 8 / housing assistance"
        RELOCATION = "RELOCATION", "Relocation"
        OTHER = "OTHER", "Other"

    class Source(models.TextChoices):
        FURNISHED_FINDER = "FURNISHED_FINDER", "Furnished Finder"
        ZILLOW = "ZILLOW", "Zillow"
        APARTMENTS = "APARTMENTS", "Apartments.com"
        FACEBOOK = "FACEBOOK", "Facebook"
        INSTAGRAM = "INSTAGRAM", "Instagram"
        WEBSITE = "WEBSITE", "Website"
        PHONE = "PHONE", "Phone"
        REFERRAL = "REFERRAL", "Referral"
        CORPORATE_PARTNER = "CORPORATE_PARTNER", "Corporate housing partner"
        INSURANCE_CARRIER = "INSURANCE_CARRIER", "Insurance carrier"
        HOUSING_AUTHORITY = "HOUSING_AUTHORITY", "Housing authority"
        REALTOR = "REALTOR", "Realtor"
        OWNER_REFERRAL = "OWNER_REFERRAL", "Owner referral"
        MANUAL = "MANUAL", "Manual"
        OTHER = "OTHER", "Other"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="leads")
    property = models.ForeignKey(PMProperty, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.NEW)
    lead_type = models.CharField(max_length=24, choices=LeadType.choices, default=LeadType.REGULAR)
    source = models.CharField(max_length=32, choices=Source.choices, default=Source.MANUAL)
    source_label = models.CharField(max_length=180, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    company_name = models.CharField(max_length=180, blank=True)
    requested_start = models.DateField(null=True, blank=True)
    requested_end = models.DateField(null=True, blank=True)
    adults = models.PositiveSmallIntegerField(default=1)
    children = models.PositiveSmallIntegerField(default=0)
    pets = models.PositiveSmallIntegerField(default=0)
    pet_notes = models.CharField(max_length=255, blank=True)
    furnished_requested = models.BooleanField(default=False)
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    summary = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    classification_confidence = models.PositiveSmallIntegerField(default=0)
    classification_reason = models.CharField(max_length=255, blank=True)
    mailbox_connection_id = models.CharField(max_length=64, blank=True)
    external_thread_id = models.CharField(max_length=255, blank=True)
    source_subject = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_pm_leads")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_leads")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["workspace", "stage"]),
            models.Index(fields=["workspace", "lead_type"]),
            models.Index(fields=["workspace", "source"]),
            models.Index(fields=["workspace", "email"]),
        ]

    @builtins.property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.company_name or self.email or "Lead"


class PMLeadMessage(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        OUTBOUND = "OUTBOUND", "Outbound"
        INTERNAL = "INTERNAL", "Internal note"

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        APP = "APP", "SyncWorks"
        PHONE = "PHONE", "Phone"
        OTHER = "OTHER", "Other"

    lead = models.ForeignKey(PMLead, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.INBOUND)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.EMAIL)
    sender_name = models.CharField(max_length=180, blank=True)
    sender_email = models.EmailField(blank=True)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    external_message_id = models.CharField(max_length=255, blank=True)
    external_thread_id = models.CharField(max_length=255, blank=True)
    mailbox_connection_id = models.CharField(max_length=64, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="pm_lead_messages")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["lead", "external_message_id"], condition=~models.Q(external_message_id=""), name="uniq_pm_lead_external_message")
        ]
