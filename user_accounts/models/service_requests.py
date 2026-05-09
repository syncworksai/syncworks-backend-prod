# user_accounts/models/service_requests.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .categories import ServiceCategory
from .business import Business


class ServiceRequest(models.Model):
    """
    Customer creates a request for work.
    This is turned into a Ticket (1:1) and then routed to an SBO or Marketplace.
    """

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        SENT = "SENT", "Sent"
        MATCHED = "MATCHED", "Matched"
        CANCELLED = "CANCELLED", "Cancelled"
        CLOSED = "CLOSED", "Closed"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="service_requests",
    )

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
    )

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")

    # Native marketplace intake fields.
    # These are parsed from the compatibility "SyncWorks Intake:" JSON block
    # embedded in description, while preserving the original description.
    priority = models.CharField(max_length=50, blank=True, default="")
    needed_by_date = models.DateField(null=True, blank=True)
    preferred_time_window = models.CharField(max_length=120, blank=True, default="")
    preferred_start_date = models.DateField(null=True, blank=True)
    preferred_end_date = models.DateField(null=True, blank=True)
    intake_payload = models.JSONField(default=dict, blank=True)

    # These exist in your ServiceRequestSerializer fields
    address = models.CharField(max_length=255, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    # Preferred provider (SBO user id). Optional.
    preferred_sbo_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preferred_service_requests",
    )

    # Direct-to-business routing (Business Cards “Schedule again”)
    target_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="targeted_service_requests",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"ServiceRequest #{self.id} ({self.status})"


class ServiceRequestPhoto(models.Model):
    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to="service_requests/")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"ServiceRequestPhoto #{self.id} (request={self.request_id})"