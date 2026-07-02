from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models
from django.utils import timezone


def _lineage_key() -> str:
    return uuid.uuid4().hex


class PartnerInvoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"
        DISPUTED = "DISPUTED", "Disputed"
        VOID = "VOID", "Void"

    class FeeTreatment(models.TextChoices):
        LINKED_SETTLEMENT = (
            "LINKED_SETTLEMENT",
            "Linked settlement — no duplicate platform fee",
        )
        INDEPENDENT_B2B = (
            "INDEPENDENT_B2B",
            "Independent B2B transaction",
        )
        MANUAL_EXEMPT = "MANUAL_EXEMPT", "Manually exempt"

    work_ticket = models.ForeignKey(
        "user_accounts.PartnerWorkTicket",
        on_delete=models.PROTECT,
        related_name="partner_invoices",
    )
    issuing_business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.PROTECT,
        related_name="partner_invoices_issued",
    )
    paying_business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.PROTECT,
        related_name="partner_invoices_payable",
    )

    invoice_number = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    line_items = models.JSONField(default=list, blank=True)

    subtotal_cents = models.PositiveBigIntegerField(default=0)
    tax_cents = models.PositiveBigIntegerField(default=0)
    total_cents = models.PositiveBigIntegerField(default=0)
    amount_paid_cents = models.PositiveBigIntegerField(default=0)

    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    fee_treatment = models.CharField(
        max_length=24,
        choices=FeeTreatment.choices,
        default=FeeTreatment.LINKED_SETTLEMENT,
    )
    fee_lineage_key = models.CharField(
        max_length=64,
        unique=True,
        default=_lineage_key,
        editable=False,
    )
    platform_fee_rate_bps = models.PositiveIntegerField(default=100)
    platform_fee_amount_cents = models.PositiveBigIntegerField(default=0)
    processor_fee_amount_cents = models.PositiveBigIntegerField(default=0)

    due_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_invoices_created",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_invoices_approved",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["issuing_business", "status", "created_at"],
                name="ua_b2binv_issuer_status_idx",
            ),
            models.Index(
                fields=["paying_business", "status", "due_date"],
                name="ua_b2binv_payer_status_idx",
            ),
            models.Index(
                fields=["work_ticket", "status", "created_at"],
                name="ua_b2binv_work_status_idx",
            ),
        ]

    @property
    def balance_due_cents(self) -> int:
        return max(int(self.total_cents) - int(self.amount_paid_cents), 0)

    def recompute_platform_fee(self) -> None:
        if self.fee_treatment != self.FeeTreatment.INDEPENDENT_B2B:
            self.platform_fee_amount_cents = 0
            return
        raw = (
            Decimal(int(self.total_cents or 0))
            * Decimal(int(self.platform_fee_rate_bps or 0))
            / Decimal("10000")
        )
        self.platform_fee_amount_cents = int(
            raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    def save(self, *args, **kwargs):
        self.recompute_platform_fee()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.invoice_number or f"Partner invoice #{self.id}"


class PartnerPayment(models.Model):
    class Method(models.TextChoices):
        CREDIT_CARD = "CREDIT_CARD", "Credit card"
        DEBIT_CARD = "DEBIT_CARD", "Debit card"
        ACH = "ACH", "ACH"
        STRIPE = "STRIPE", "Stripe"
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        ZELLE = "ZELLE", "Zelle"
        CASH_APP = "CASH_APP", "Cash App"
        VENMO = "VENMO", "Venmo"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"
        VOID = "VOID", "Void"

    invoice = models.ForeignKey(
        PartnerInvoice,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount_cents = models.PositiveBigIntegerField()
    method = models.CharField(
        max_length=24,
        choices=Method.choices,
        default=Method.ACH,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    processor_fee_amount_cents = models.PositiveBigIntegerField(default=0)
    external_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    receipt_url = models.URLField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    stripe_charge_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    stripe_transfer_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_payments_recorded",
        null=True,
        blank=True,
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_payments_confirmed",
        null=True,
        blank=True,
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        indexes = [
            models.Index(
                fields=["invoice", "status", "recorded_at"],
                name="ua_b2bpay_invoice_status_idx",
            ),
            models.Index(
                fields=["method", "status", "recorded_at"],
                name="ua_b2bpay_method_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Partner payment #{self.id} — {self.amount_cents}"


class PartnerPaymentAllocation(models.Model):
    partner_payment = models.ForeignKey(
        PartnerPayment,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    customer_invoice = models.ForeignKey(
        "user_accounts.Invoice",
        on_delete=models.SET_NULL,
        related_name="partner_payment_allocations",
        null=True,
        blank=True,
    )
    source_ticket = models.ForeignKey(
        "user_accounts.Ticket",
        on_delete=models.SET_NULL,
        related_name="partner_payment_allocations",
        null=True,
        blank=True,
    )
    allocated_amount_cents = models.PositiveBigIntegerField(default=0)
    lineage_key = models.CharField(max_length=64, db_index=True)
    platform_fee_already_assessed = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["lineage_key", "created_at"],
                name="ua_b2balloc_lineage_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Allocation {self.id}: "
            f"{self.allocated_amount_cents} cents"
        )
