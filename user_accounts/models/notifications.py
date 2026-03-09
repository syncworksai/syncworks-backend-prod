from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Notification(models.Model):
    """
    Internal "Inbox" item.

    Used for:
    - God Mode / system -> customer messages
    - Ticket updates
    - Billing updates
    - Broadcasts / promos / reminders
    """

    TYPE_SYSTEM = "SYSTEM"
    TYPE_BROADCAST = "BROADCAST"
    TYPE_TICKET = "TICKET"
    TYPE_BILLING = "BILLING"
    TYPE_MESSAGE = "MESSAGE"   # God Mode -> Customer message
    TYPE_REMINDER = "REMINDER" # future: reminders
    TYPE_PROMO = "PROMO"       # future: promos/ads

    TYPE_CHOICES = (
        (TYPE_SYSTEM, "System"),
        (TYPE_BROADCAST, "Broadcast"),
        (TYPE_TICKET, "Ticket"),
        (TYPE_BILLING, "Billing"),
        (TYPE_MESSAGE, "Message"),
        (TYPE_REMINDER, "Reminder"),
        (TYPE_PROMO, "Promo"),
    )

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_sent",
    )

    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default=TYPE_SYSTEM)
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    # ✅ Archive support (Inbox behavior)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Notification(to={self.recipient_id}, type={self.type}, read={self.is_read})"

    def mark_read(self) -> None:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def archive(self) -> None:
        if not self.archived_at:
            self.archived_at = timezone.now()
            self.save(update_fields=["archived_at"])

    def unarchive(self) -> None:
        if self.archived_at:
            self.archived_at = None
            self.save(update_fields=["archived_at"])


class PlatformNewsItem(models.Model):
    """
    Internal marketing / news reel / tips / ads.
    Managed by God Mode.
    Supports: scheduling + expiration + geo targeting by ZIP.
    """

    KIND_NEWS = "NEWS"
    KIND_TIP = "TIP"
    KIND_AD = "AD"
    KIND_ALERT = "ALERT"

    KIND_CHOICES = (
        (KIND_NEWS, "News"),
        (KIND_TIP, "Tip"),
        (KIND_AD, "Ad"),
        (KIND_ALERT, "Alert"),
    )

    TARGET_ALL = "ALL"
    TARGET_CUSTOMER = "CUSTOMER"
    TARGET_SBO = "SBO"
    TARGET_PM = "PM"

    TARGET_CHOICES = (
        (TARGET_ALL, "All"),
        (TARGET_CUSTOMER, "Customers"),
        (TARGET_SBO, "SBOs"),
        (TARGET_PM, "Property Managers"),
    )

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_NEWS)

    title = models.CharField(max_length=140, blank=True, default="")
    body = models.CharField(max_length=300, blank=True, default="")

    image = models.ImageField(upload_to="newsreel/", blank=True, null=True)
    link_url = models.URLField(blank=True, default="")

    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    target_scope = models.CharField(max_length=16, choices=TARGET_CHOICES, default=TARGET_ALL)
    target_zip_codes = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PlatformNewsItem(kind={self.kind}, active={self.is_active}, scope={self.target_scope})"

    def is_live(self) -> bool:
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True
