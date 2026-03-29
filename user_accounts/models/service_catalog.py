from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class ServiceCatalogItem(models.Model):
    class ItemType(models.TextChoices):
        SERVICE = "SERVICE", "Service"
        PRODUCT = "PRODUCT", "Product"
        FEE = "FEE", "Fee"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="service_catalog_items",
    )

    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")

    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.SERVICE,
    )

    unit_label = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Examples: each, hour, visit, ride, yard, room",
    )
    default_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))

    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    requires_quote = models.BooleanField(
        default=False,
        help_text="If true, this item is intended to go through quote approval before invoicing.",
    )
    allow_direct_checkout = models.BooleanField(
        default=False,
        help_text="If true, this item can later be used in direct-order / fixed-price flows.",
    )

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name", "id"]
        indexes = [
            models.Index(fields=["business", "is_active", "sort_order"]),
            models.Index(fields=["business", "item_type", "is_active"]),
            models.Index(fields=["business", "name"]),
            models.Index(fields=["business", "sku"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "sku"],
                condition=~models.Q(sku=""),
                name="uniq_service_catalog_item_business_sku_nonblank",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (biz={self.business_id})"

    @property
    def gross_profit_per_unit(self) -> Decimal:
        return (Decimal(self.unit_price or 0) - Decimal(self.unit_cost or 0)).quantize(Decimal("0.01"))

    @property
    def gross_margin_pct(self) -> Decimal:
        price = Decimal(self.unit_price or 0)
        if price <= 0:
            return Decimal("0.00")
        margin = ((price - Decimal(self.unit_cost or 0)) / price) * Decimal("100")
        return margin.quantize(Decimal("0.01"))