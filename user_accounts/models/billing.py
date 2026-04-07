from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone

from user_accounts.models.tickets import Ticket
from user_accounts.models.service_catalog import ServiceCatalogItem


TWOPLACES = Decimal("0.01")


def _d(v, default: str = "0.00") -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(default)


def _q(v: Decimal) -> Decimal:
    return _d(v).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class Invoice(models.Model):
    """
    Invoice generated from a Ticket.

    Production flow:
      - Invoice starts as DRAFT
      - SBO marks it ready -> SENT
      - Customer pays -> PAID
      - Platform fee is tracked on the invoice for deterministic KPI math
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    class PaymentMethod(models.TextChoices):
        CARD = "CARD", "Card"
        CASH = "CASH", "Cash"
        OTHER = "OTHER", "Other"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    title = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    due_date = models.DateField(null=True, blank=True)

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CARD,
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    paid_at = models.DateTimeField(null=True, blank=True)

    platform_fee_rate_bps = models.PositiveIntegerField(default=100)  # 1.00%
    platform_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    platform_fee_collected = models.BooleanField(default=False)
    platform_fee_collected_at = models.DateTimeField(null=True, blank=True)

    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, default="")
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    stripe_charge_id = models.CharField(max_length=255, blank=True, default="")
    stripe_transfer_id = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["ticket", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["payment_method", "status"]),
        ]
        ordering = ["-created_at"]

    def recompute_platform_fee(self) -> None:
        rate = Decimal(self.platform_fee_rate_bps) / Decimal("10000")
        self.platform_fee_amount = _q(Decimal(self.total or 0) * rate)

    def recompute_totals_from_lines(self, *, save: bool = False) -> None:
        subtotal = Decimal("0.00")
        try:
            for line in self.line_items.all():
                subtotal += _d(line.line_subtotal or "0.00")
        except Exception:
            pass

        self.subtotal = _q(subtotal)
        self.total = _q(_d(self.subtotal) + _d(self.tax))
        self.recompute_platform_fee()

        if save:
            update_fields = ["subtotal", "total", "platform_fee_amount"]
            if hasattr(self, "updated_at"):
                update_fields.append("updated_at")
            self.save(update_fields=update_fields)

    def mark_paid(self, *, method: str | None = None) -> None:
        if method:
            self.payment_method = method
        self.status = self.Status.PAID
        self.amount_paid = self.total
        self.paid_at = timezone.now()
        self.recompute_platform_fee()

        if self.payment_method == self.PaymentMethod.CARD:
            self.platform_fee_collected = True
            self.platform_fee_collected_at = timezone.now()

    def mark_platform_fee_collected(self) -> None:
        self.platform_fee_collected = True
        self.platform_fee_collected_at = timezone.now()

    def save(self, *args, **kwargs):
        try:
            self.subtotal = _q(self.subtotal)
            self.tax = _q(self.tax)
            self.total = _q(self.total)
            self.recompute_platform_fee()
        except Exception:
            pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice #{self.id} ({self.status})"


class InvoiceLineItem(models.Model):
    class ItemType(models.TextChoices):
        SERVICE = "SERVICE", "Service"
        PRODUCT = "PRODUCT", "Product"
        FEE = "FEE", "Fee"
        CUSTOM = "CUSTOM", "Custom"

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="line_items",
    )

    catalog_item = models.ForeignKey(
        ServiceCatalogItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_line_items",
    )

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.CUSTOM)
    unit_label = models.CharField(max_length=32, blank=True, default="")

    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    line_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["invoice", "sort_order"]),
            models.Index(fields=["invoice", "catalog_item"]),
        ]

    def recompute_line_subtotal(self) -> None:
        qty = _d(self.quantity, "1.00")
        if qty <= 0:
            qty = Decimal("1.00")
        self.quantity = _q(qty)
        self.unit_price = _q(self.unit_price)
        self.unit_cost = _q(self.unit_cost)
        self.line_subtotal = _q(_d(self.quantity) * _d(self.unit_price))

    @property
    def line_cost_total(self) -> Decimal:
        return _q(_d(self.quantity) * _d(self.unit_cost))

    @property
    def line_profit_total(self) -> Decimal:
        return _q(_d(self.line_subtotal) - self.line_cost_total)

    @property
    def line_margin_pct(self) -> Decimal:
        revenue = _d(self.line_subtotal)
        if revenue <= 0:
            return Decimal("0.00")
        return _q((self.line_profit_total / revenue) * Decimal("100"))

    def save(self, *args, **kwargs):
        self.recompute_line_subtotal()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} x {self.quantity} (invoice={self.invoice_id})"