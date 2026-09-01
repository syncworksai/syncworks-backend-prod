from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class StorefrontMerchant(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("ACTIVE", "Active"),
        ("DISABLED", "Disabled"),
    ]
    KIND_CHOICES = [
        ("AMAZON", "Amazon"),
        ("DIRECT", "Direct partner"),
        ("OTHER", "Other"),
    ]

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="OTHER")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    allowed_domains = models.JSONField(blank=True, default=list)
    affiliate_tag_env_key = models.CharField(max_length=120, blank=True, default="")
    disclosure = models.CharField(max_length=500, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class StorefrontClick(models.Model):
    merchant = models.ForeignKey(StorefrontMerchant, on_delete=models.PROTECT, related_name="clicks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL, related_name="storefront_clicks")
    business = models.ForeignKey("user_accounts.Business", blank=True, null=True, on_delete=models.SET_NULL, related_name="storefront_clicks")
    module = models.CharField(max_length=40, default="DIRECT_STOREFRONT")
    need_reference = models.CharField(max_length=120, blank=True, default="")
    project_reference = models.CharField(max_length=120, blank=True, default="")
    product_reference = models.CharField(max_length=180, blank=True, default="")
    outbound_url = models.URLField(max_length=1500)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "created_at"], name="store_click_merchant_idx"),
            models.Index(fields=["module", "created_at"], name="store_click_module_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.slug} {self.module} click"


class StorefrontEarning(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("PAID", "Paid"),
        ("REVERSED", "Reversed"),
    ]

    merchant = models.ForeignKey(StorefrontMerchant, on_delete=models.PROTECT, related_name="earnings")
    click = models.ForeignKey(StorefrontClick, blank=True, null=True, on_delete=models.SET_NULL, related_name="earnings")
    module = models.CharField(max_length=40, default="DIRECT_STOREFRONT")
    external_order_reference = models.CharField(max_length=255, blank=True, default="")
    gross_sales_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    occurred_on = models.DateField(default=timezone.localdate)
    reported_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]
        indexes = [
            models.Index(fields=["merchant", "status"], name="store_earn_merchant_idx"),
            models.Index(fields=["module", "occurred_on"], name="store_earn_module_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "external_order_reference"],
                condition=~models.Q(external_order_reference=""),
                name="store_earning_order_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.slug} {self.commission_amount} {self.status}"
