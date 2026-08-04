from django.conf import settings
from django.db import models


class PMPropertyDocument(models.Model):
    class Category(models.TextChoices):
        LEASE = "LEASE", "Lease agreement"
        LEASE_ADDENDUM = "LEASE_ADDENDUM", "Lease addendum"
        MANAGEMENT_AGREEMENT = "MANAGEMENT_AGREEMENT", "Property management agreement"
        OWNERSHIP = "OWNERSHIP", "Ownership / management change"
        SECTION8 = "SECTION8", "Section 8 / housing authority"
        RENT_INCREASE = "RENT_INCREASE", "Rent increase request"
        MOVE_IN_INSPECTION = "MOVE_IN_INSPECTION", "Move-in inspection"
        MOVE_OUT_INSPECTION = "MOVE_OUT_INSPECTION", "Move-out inspection"
        SECURITY_DEPOSIT = "SECURITY_DEPOSIT", "Security deposit"
        PAYMENT_ARRANGEMENT = "PAYMENT_ARRANGEMENT", "Payment arrangement"
        NOTICE = "NOTICE", "Notice / legal"
        OPERATING_STATEMENT = "OPERATING_STATEMENT", "Operating statement"
        INSURANCE = "INSURANCE", "Insurance"
        IDENTITY_TAX = "IDENTITY_TAX", "Identity / tax"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PENDING_SIGNATURE = "PENDING_SIGNATURE", "Pending signature"
        SIGNED = "SIGNED", "Signed"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        EXPIRED = "EXPIRED", "Expired"
        ARCHIVED = "ARCHIVED", "Archived"

    workspace = models.ForeignKey("pm_workspace.PMWorkspace", on_delete=models.CASCADE, related_name="property_documents")
    property = models.ForeignKey("pm_workspace.PMProperty", on_delete=models.CASCADE, related_name="documents")
    tenant = models.ForeignKey("pm_workspace.PMTenant", null=True, blank=True, on_delete=models.SET_NULL, related_name="property_documents")
    lease = models.ForeignKey("pm_workspace.PMLease", null=True, blank=True, on_delete=models.SET_NULL, related_name="property_documents")
    property_owner = models.ForeignKey("pm_workspace.PMPropertyOwner", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    category = models.CharField(max_length=40, choices=Category.choices)
    title = models.CharField(max_length=220)
    document = models.FileField(upload_to="pm/documents/%Y/%m/", null=True, blank=True)
    source_url = models.URLField(blank=True)
    source_name = models.CharField(max_length=255, blank=True)
    state_code = models.CharField(max_length=2, blank=True)
    housing_authority = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACTIVE)
    effective_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    signed_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    checklist_key = models.CharField(max_length=100, blank=True)
    extracted_terms = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_pm_property_documents")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["workspace", "property", "category"]),
            models.Index(fields=["workspace", "status"]),
        ]
