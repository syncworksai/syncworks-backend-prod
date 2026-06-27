from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.tickets import Ticket
from user_accounts.models.assets import TrackableAsset


class BusinessResource(models.Model):
    class ResourceType(models.TextChoices):
        BAY = "BAY", "Bay"
        TRUCK = "TRUCK", "Truck"
        CREW = "CREW", "Crew"
        STATION = "STATION", "Station"
        ROOM = "ROOM", "Room"
        TABLE = "TABLE", "Table"
        SHELF = "SHELF", "Shelf"
        MACHINE = "MACHINE", "Machine"
        REGISTER = "REGISTER", "Register"
        HOLDING_AREA = "HOLDING_AREA", "Holding Area"
        TOOL = "TOOL", "Tool"
        CUSTOM = "CUSTOM", "Custom"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        OCCUPIED = "OCCUPIED", "Occupied"
        RESERVED = "RESERVED", "Reserved"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        INACTIVE = "INACTIVE", "Inactive"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="operational_resources",
    )
    name = models.CharField(max_length=160)
    resource_type = models.CharField(
        max_length=24,
        choices=ResourceType.choices,
        default=ResourceType.CUSTOM,
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    location = models.CharField(max_length=160, blank=True, default="")
    capacity = models.PositiveIntegerField(default=1)
    skills = models.JSONField(default=list, blank=True)
    availability = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_resources_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["resource_type", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="ua_business_resource_name_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "resource_type", "is_active"],
                name="ua_resource_business_type_idx",
            ),
            models.Index(
                fields=["business", "status"],
                name="ua_res_business_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.resource_type})"


class ResourceAssignment(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    resource = models.ForeignKey(
        BusinessResource,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="resource_assignments",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True, default="")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_assignments_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "ticket"],
                condition=models.Q(status__in=["PLANNED", "ACTIVE"]),
                name="ua_resource_ticket_open_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["resource", "status", "starts_at"],
                name="ua_res_assign_status_idx",
            ),
            models.Index(
                fields=["ticket", "status"],
                name="ua_ticket_resource_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resource_id} -> Ticket {self.ticket_id}"


class ResourceMovement(models.Model):
    resource = models.ForeignKey(
        BusinessResource,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    asset = models.ForeignKey(
        TrackableAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_movements",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_movements",
    )
    from_location = models.CharField(max_length=160, blank=True, default="")
    to_location = models.CharField(max_length=160)
    reason = models.CharField(max_length=255, blank=True, default="")
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_movements_created",
    )
    moved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-moved_at", "-id"]
        indexes = [
            models.Index(
                fields=["resource", "moved_at"],
                name="ua_resource_movement_time_idx",
            ),
            models.Index(
                fields=["asset", "moved_at"],
                name="ua_asset_movement_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.resource_id}: {self.from_location} -> {self.to_location}"
