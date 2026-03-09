# backend/user_accounts/models/pm_section8.py
from __future__ import annotations

from django.conf import settings
from django.db import models

from user_accounts.models.business import Business
from user_accounts.models.pm_property import PMProperty
from user_accounts.models.pm_unit import PMUnit
from user_accounts.models.pm_tenant import PMTenant


class PMSection8Case(models.Model):
    """
    Section 8 workflow tracker (per tenant + unit).
    Designed for reminders + dashboards:
      - Recertification due
      - Inspection due / failed
      - HAP contract dates
      - Rent split (tenant portion vs subsidy)
      - Housing Authority + caseworker contacts

    ✅ Packet QA / checklist:
      - packet_items: JSON map of required docs / checklist items (bools)
      - packet_ready: quick flag for "approved to submit"
      - packet_last_reviewed_at: when PM last checked the packet
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PENDING = "PENDING", "Pending / Onboarding"
        SUSPENDED = "SUSPENDED", "Suspended"
        TERMINATED = "TERMINATED", "Terminated"
        CLOSED = "CLOSED", "Closed"

    class InspectionStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        SCHEDULED = "SCHEDULED", "Scheduled"
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        REINSPECTION = "REINSPECTION", "Reinspection Needed"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_section8_cases")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="section8_cases")
    unit = models.ForeignKey(PMUnit, on_delete=models.CASCADE, related_name="section8_cases")
    tenant = models.ForeignKey(PMTenant, on_delete=models.CASCADE, related_name="section8_cases")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Housing Authority info
    housing_authority_name = models.CharField(max_length=200, blank=True, default="")
    housing_authority_phone = models.CharField(max_length=40, blank=True, default="")
    housing_authority_email = models.EmailField(blank=True, default="")

    caseworker_name = models.CharField(max_length=200, blank=True, default="")
    caseworker_phone = models.CharField(max_length=40, blank=True, default="")
    caseworker_email = models.EmailField(blank=True, default="")

    # Voucher / contract identifiers
    voucher_number = models.CharField(max_length=80, blank=True, default="")
    hap_contract_number = models.CharField(max_length=80, blank=True, default="")

    # Key dates (automation anchors)
    hap_start_date = models.DateField(null=True, blank=True)
    hap_end_date = models.DateField(null=True, blank=True)

    recert_due_date = models.DateField(null=True, blank=True)  # annual recertification target
    recert_submitted_date = models.DateField(null=True, blank=True)
    recert_approved_date = models.DateField(null=True, blank=True)

    inspection_status = models.CharField(
        max_length=20,
        choices=InspectionStatus.choices,
        default=InspectionStatus.UNKNOWN,
    )
    inspection_scheduled_date = models.DateField(null=True, blank=True)
    inspection_completed_date = models.DateField(null=True, blank=True)
    inspection_fail_reasons = models.TextField(blank=True, default="")

    # Rent split (monthly)
    contract_rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tenant_portion = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    subsidy_portion = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    # ✅ NEW: Packet QA checklist fields
    packet_items = models.JSONField(default=dict, blank=True)
    packet_ready = models.BooleanField(default=False)
    packet_last_reviewed_at = models.DateTimeField(null=True, blank=True)

    # audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_section8_cases",
    )

    class Meta:
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "recert_due_date"]),
            models.Index(fields=["business", "inspection_status"]),
            # optional: these help packet filters later
            models.Index(fields=["business", "packet_ready"]),
        ]
        constraints = [
            # one active case per tenant+unit (prevents duplicates)
            models.UniqueConstraint(fields=["business", "tenant", "unit"], name="uniq_section8_case_tenant_unit_per_biz"),
        ]

    def __str__(self) -> str:
        return f"Section8Case(biz={self.business_id}, tenant={self.tenant_id}, unit={self.unit_id}, status={self.status})"
