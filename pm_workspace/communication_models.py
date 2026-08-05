from django.conf import settings
from django.db import models

from .models import PMLedgerEntry, PMLease, PMProperty, PMTenant, PMWorkspace
from .owner_models import PMPropertyOwner


class PMConversation(models.Model):
    class Category(models.TextChoices):
        TENANT = "TENANT", "Tenant"
        INVESTOR = "INVESTOR", "Investor"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        INTERNAL = "INTERNAL", "Internal team"
        COLLECTIONS = "COLLECTIONS", "Collections and legal"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        WAITING_PM = "WAITING_PM", "Waiting on PM"
        WAITING_REQUESTER = "WAITING_REQUESTER", "Waiting on requester"
        RESOLVED = "RESOLVED", "Resolved"

    workspace = models.ForeignKey(PMWorkspace, on_delete=models.CASCADE, related_name="conversations")
    category = models.CharField(max_length=20, choices=Category.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    subject = models.CharField(max_length=220)
    tenant = models.ForeignKey(PMTenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    property = models.ForeignKey(PMProperty, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    property_owner = models.ForeignKey(PMPropertyOwner, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    lease = models.ForeignKey(PMLease, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    ledger_entry = models.ForeignKey(PMLedgerEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="information_requests")
    work_order = models.ForeignKey("PMWorkOrder", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    tenant_case = models.ForeignKey("PMTenantCase", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    requester_name = models.CharField(max_length=180, blank=True)
    requester_email = models.EmailField(blank=True)
    internal_only = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_conversations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["workspace", "category", "status"])]


class PMConversationMessage(models.Model):
    class SenderRole(models.TextChoices):
        PM = "PM", "Property management"
        TENANT = "TENANT", "Tenant"
        INVESTOR = "INVESTOR", "Investor"
        INTERNAL = "INTERNAL", "Internal team"
        SYSTEM = "SYSTEM", "System"

    conversation = models.ForeignKey(PMConversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="pm_conversation_messages")
    sender_role = models.CharField(max_length=16, choices=SenderRole.choices)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
