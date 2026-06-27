from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.tickets import Ticket


class TrackableAsset(models.Model):
    class AssetType(models.TextChoices):
        VEHICLE = "VEHICLE", "Vehicle"
        EQUIPMENT = "EQUIPMENT", "Equipment"
        PROPERTY = "PROPERTY", "Property"
        PRODUCT = "PRODUCT", "Product"
        INVENTORY = "INVENTORY", "Inventory"
        ORDER = "ORDER", "Order"
        TOOL = "TOOL", "Tool"
        APPLIANCE = "APPLIANCE", "Appliance"
        SYSTEM = "SYSTEM", "System"
        CUSTOM = "CUSTOM", "Custom"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        IN_SERVICE = "IN_SERVICE", "In Service"
        HOLDING = "HOLDING", "Holding"
        BLOCKED = "BLOCKED", "Blocked"
        RETIRED = "RETIRED", "Retired"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="trackable_assets",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trackable_assets",
    )
    asset_type = models.CharField(max_length=24, choices=AssetType.choices, default=AssetType.CUSTOM)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACTIVE)
    make = models.CharField(max_length=100, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    location = models.CharField(max_length=160, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trackable_assets_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["business", "asset_type", "is_active"], name="ua_asset_business_type_idx"),
            models.Index(fields=["business", "customer"], name="ua_asset_business_customer_idx"),
            models.Index(fields=["business", "status"], name="ua_asset_business_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.asset_type})"


class AssetIdentifier(models.Model):
    class IdentifierType(models.TextChoices):
        SYNCWORKS_QR = "SYNCWORKS_QR", "SyncWorks QR"
        BARCODE = "BARCODE", "Barcode"
        UPC = "UPC", "UPC"
        SKU = "SKU", "SKU"
        VIN = "VIN", "VIN"
        LICENSE_PLATE = "LICENSE_PLATE", "License Plate"
        SERIAL_NUMBER = "SERIAL_NUMBER", "Serial Number"
        VENDOR_PART_NUMBER = "VENDOR_PART_NUMBER", "Vendor Part Number"
        KEY_TAG = "KEY_TAG", "Key Tag"
        PURCHASE_ORDER = "PURCHASE_ORDER", "Purchase Order"
        TABLE_CODE = "TABLE_CODE", "Table Code"
        SHELF_CODE = "SHELF_CODE", "Shelf Code"
        CUSTOM = "CUSTOM", "Custom"

    asset = models.ForeignKey(TrackableAsset, on_delete=models.CASCADE, related_name="identifiers")
    identifier_type = models.CharField(max_length=32, choices=IdentifierType.choices, default=IdentifierType.CUSTOM)
    value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=255)
    source = models.CharField(max_length=120, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-is_primary", "identifier_type", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "identifier_type", "normalized_value"],
                name="ua_asset_identifier_asset_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["identifier_type", "normalized_value"], name="ua_asset_identifier_lookup_idx"),
            models.Index(fields=["asset", "is_active"], name="ua_asset_identifier_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.identifier_type}: {self.value}"


class TicketAssetLink(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        RELATED = "RELATED", "Related"
        MATERIAL = "MATERIAL", "Material"
        RESOURCE = "RESOURCE", "Resource"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="asset_links")
    asset = models.ForeignKey(TrackableAsset, on_delete=models.CASCADE, related_name="ticket_links")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PRIMARY)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_asset_links_created",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["ticket_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "asset", "role"],
                name="ua_ticket_asset_role_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["ticket", "role"], name="ua_ticket_asset_role_idx"),
            models.Index(fields=["asset", "created_at"], name="ua_asset_ticket_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Ticket {self.ticket_id} -> Asset {self.asset_id}"
