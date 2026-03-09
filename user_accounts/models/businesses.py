from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Business(models.Model):
    """
    A business owned by an SBO user.
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_businesses")
    name = models.CharField(max_length=140)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return self.name


class BusinessMember(models.Model):
    """
    Employee seat inside a business.
    """

    class MemberRole(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        DISPATCH = "DISPATCH", "Dispatch"
        TECHNICIAN = "TECHNICIAN", "Technician"
        ACCOUNTING = "ACCOUNTING", "Accounting"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_memberships")

    role = models.CharField(max_length=20, choices=MemberRole.choices, default=MemberRole.TECHNICIAN)

    # permission toggles
    can_view_invoices = models.BooleanField(default=False)
    can_send_quotes = models.BooleanField(default=False)
    can_assign_tickets = models.BooleanField(default=False)
    can_post_internal_messages = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    terminated_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("business", "user")

    def __str__(self) -> str:
        return f"{self.business_id}:{self.user_id} ({self.role})"
