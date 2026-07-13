from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from platform_affiliates.choices import (
    AffiliateStatus,
    AttributionSource,
    CommissionStatus,
    PayoutBatchStatus,
    PayoutProvider,
    RevenueSource,
)
from platform_affiliates.constants import (
    DEFAULT_AFFILIATE_COMMISSION_RATE_BPS,
    DEFAULT_AGREEMENT_VERSION,
)


class AffiliatePartner(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="affiliate_partner",
    )
    name = models.CharField(max_length=180)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, default="")
    address_line_1 = models.CharField(max_length=220, blank=True, default="")
    address_line_2 = models.CharField(max_length=220, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=2, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")
    code = models.CharField(max_length=32, unique=True)
    status = models.CharField(
        max_length=20,
        choices=AffiliateStatus.choices,
        default=AffiliateStatus.PENDING,
    )
    commission_rate_bps = models.PositiveIntegerField(
        default=DEFAULT_AFFILIATE_COMMISSION_RATE_BPS,
        help_text="1000 bps = 10% of net SyncWorks revenue.",
    )
    payout_provider = models.CharField(
        max_length=20,
        choices=PayoutProvider.choices,
        default=PayoutProvider.MANUAL,
    )
    payout_email = models.EmailField(blank=True, default="")
    payout_notes = models.TextField(blank=True, default="")
    external_payout_reference = models.CharField(max_length=255, blank=True, default="")
    application_notes = models.TextField(blank=True, default="")
    referral_strategy = models.TextField(blank=True, default="")
    agreement_version = models.CharField(
        max_length=64,
        blank=True,
        default=DEFAULT_AGREEMENT_VERSION,
    )
    agreement_accepted_at = models.DateTimeField(blank=True, null=True)
    agreement_accepted_ip = models.GenericIPAddressField(blank=True, null=True)
    agreement_accepted_user_agent = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="approved_affiliates",
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class AffiliateAgreementTemplate(models.Model):
    title = models.CharField(max_length=180)
    version = models.CharField(max_length=64, unique=True)
    body = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} - {self.version}"


class AffiliateAgreementAcceptance(models.Model):
    affiliate = models.ForeignKey(
        AffiliatePartner,
        on_delete=models.CASCADE,
        related_name="agreement_acceptances",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="affiliate_agreement_acceptances",
    )
    agreement_version = models.CharField(max_length=64)
    accepted_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-accepted_at"]

    def __str__(self) -> str:
        return f"{self.affiliate.code} accepted {self.agreement_version}"


class ReferralAttribution(models.Model):
    business = models.OneToOneField(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="affiliate_attribution",
    )
    affiliate = models.ForeignKey(
        AffiliatePartner,
        on_delete=models.PROTECT,
        related_name="attributions",
    )
    referral_code = models.CharField(max_length=32)
    attribution_source = models.CharField(
        max_length=30,
        choices=AttributionSource.choices,
        default=AttributionSource.LINK,
    )
    locked_at = models.DateTimeField(default=timezone.now)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="assigned_affiliate_attributions",
    )
    admin_note = models.TextField(blank=True, default="")
    effective_from = models.DateField(default=timezone.localdate)
    retroactive = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.business} -> {self.affiliate.code}"


class ReferralClick(models.Model):
    affiliate = models.ForeignKey(
        AffiliatePartner,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="referral_clicks",
    )
    code = models.CharField(max_length=32)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default="")
    landing_path = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} click"


class AffiliatePayoutBatch(models.Model):
    affiliate = models.ForeignKey(
        AffiliatePartner,
        on_delete=models.PROTECT,
        related_name="payout_batches",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=20,
        choices=PayoutBatchStatus.choices,
        default=PayoutBatchStatus.DRAFT,
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    external_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]

    def __str__(self) -> str:
        return f"{self.affiliate.code} payout {self.period_start} - {self.period_end}"


class AffiliateCommissionLedger(models.Model):
    affiliate = models.ForeignKey(
        AffiliatePartner,
        on_delete=models.PROTECT,
        related_name="commission_ledger",
    )
    business = models.ForeignKey(
        "user_accounts.Business",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="affiliate_commissions",
    )
    attribution = models.ForeignKey(
        ReferralAttribution,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="commissions",
    )
    revenue_source = models.CharField(
        max_length=40,
        choices=RevenueSource.choices,
        default=RevenueSource.PLATFORM_FEE,
    )
    gross_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_syncworks_revenue_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate_bps = models.PositiveIntegerField()
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=CommissionStatus.choices,
        default=CommissionStatus.PENDING,
    )
    source_reference = models.CharField(max_length=255, blank=True, default="")
    source_date = models.DateField(default=timezone.localdate)
    payout_batch = models.ForeignKey(
        AffiliatePayoutBatch,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="commissions",
    )
    memo = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-source_date", "-created_at"]
        indexes = [
            models.Index(fields=["affiliate", "status"]),
            models.Index(fields=["revenue_source", "source_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate.code} {self.revenue_source} {self.commission_amount}"


class AffiliateAuditLog(models.Model):
    action = models.CharField(max_length=120)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="affiliate_audit_logs",
    )
    affiliate = models.ForeignKey(
        AffiliatePartner,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    business = models.ForeignKey(
        "user_accounts.Business",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="affiliate_audit_logs",
    )
    before_json = models.JSONField(blank=True, default=dict)
    after_json = models.JSONField(blank=True, default=dict)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.action
