# backend/user_accounts/models/sales_os.py
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class SalesPipeline(models.Model):
    """
    Sales OS pipeline.

    IMPORTANT:
    - Sales OS is NOT business-scoped.
    - business is optional and nullable so Sales OS can exist fully standalone.
    """

    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="sales_pipelines",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    # Optional billing config (safe defaults)
    BILLING_PER_SEAT = "per_seat"
    BILLING_FLAT = "flat"
    BILLING_CHOICES = [
        (BILLING_PER_SEAT, "Per seat"),
        (BILLING_FLAT, "Flat"),
    ]
    billing_mode = models.CharField(max_length=32, choices=BILLING_CHOICES, default=BILLING_PER_SEAT)

    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=128, blank=True, default="")
    stripe_subscription_item_id = models.CharField(max_length=128, blank=True, default="")

    # If later you implement seat-locking / billing locking, flip this from billing checks
    is_locked = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sales_pipelines",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return f"{self.name} (biz={self.business_id})"


class SalesPipelineMember(models.Model):
    """
    Seats / membership for a pipeline.
    """

    ROLE_OWNER = "OWNER"
    ROLE_MANAGER = "MANAGER"
    ROLE_AGENT = "AGENT"
    ROLE_VIEWER = "VIEWER"

    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_AGENT, "Agent"),
        (ROLE_VIEWER, "Viewer"),
    ]

    pipeline = models.ForeignKey(
        SalesPipeline,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sales_pipeline_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_AGENT)

    # Membership visibility
    is_active = models.BooleanField(default=True)

    # Billing seat toggle expected by Seat Management page
    is_active_seat = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("pipeline", "user")

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.pipeline_id} ({self.role})"


class ProspectStage(models.Model):
    """
    Configurable stages per pipeline.
    """

    pipeline = models.ForeignKey(
        SalesPipeline,
        on_delete=models.CASCADE,
        related_name="stages",
    )

    name = models.CharField(max_length=80)

    # Frontend sometimes calls this "order"
    sort_order = models.PositiveIntegerField(default=0)

    is_won = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("pipeline", "name")
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.name} (pipeline={self.pipeline_id})"


class Prospect(models.Model):
    """
    Lead / prospect card.
    """

    STATUS_OPEN = "OPEN"
    STATUS_WON = "WON"
    STATUS_LOST = "LOST"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_WON, "Won"),
        (STATUS_LOST, "Lost"),
    ]

    pipeline = models.ForeignKey(
        SalesPipeline,
        on_delete=models.CASCADE,
        related_name="prospects",
    )

    stage = models.ForeignKey(
        ProspectStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospects",
    )

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN)

    # Backwards compatibility
    name = models.CharField(max_length=160)

    # Preferred
    full_name = models.CharField(max_length=160, blank=True, default="")

    company = models.CharField(max_length=160, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # Optional light tag (Hot/Warm/etc.)
    status_label = models.CharField(max_length=80, blank=True, default="")

    next_follow_up_at = models.DateTimeField(null=True, blank=True)

    assigned_member = models.ForeignKey(
        SalesPipelineMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_prospects",
    )

    value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_prospects",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_prospects",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    @property
    def display_name(self) -> str:
        return (self.full_name or self.name or "").strip() or "Prospect"

    def __str__(self) -> str:
        return f"{self.display_name} (pipeline={self.pipeline_id})"


class ProspectAttachment(models.Model):
    """
    File attachments for prospect cards.
    """

    prospect = models.ForeignKey(
        Prospect,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    file = models.FileField(upload_to="sales/prospect_attachments/%Y/%m/%d/")
    original_name = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=120, blank=True, default="")
    size_bytes = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospect_attachments_uploaded",
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return f"Attachment {self.id} for prospect={self.prospect_id}"


class SalesEvent(models.Model):
    """
    Calendar events / appointments for Sales OS.
    """

    pipeline = models.ForeignKey(
        SalesPipeline,
        on_delete=models.CASCADE,
        related_name="events",
    )

    prospect = models.ForeignKey(
        Prospect,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    assigned_member = models.ForeignKey(
        SalesPipelineMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_events_created",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at", "id"]

    def __str__(self) -> str:
        return f"{self.title} ({self.start_at} → {self.end_at})"