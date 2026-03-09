# backend/user_accounts/models/pm_investor.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .pm_property import PMProperty


class PMInvestor(models.Model):
    """
    PM Investor profile (Owner/Investor).
    - business_id scopes multi-tenant
    - user is optional (can link a login user to an investor)
    """

    business_id = models.IntegerField(db_index=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pm_investor_profiles",
    )

    first_name = models.CharField(max_length=80, blank=True, default="")
    last_name = models.CharField(max_length=80, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["business_id", "email"]),
            models.Index(fields=["business_id", "is_active"]),
        ]

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email or f"Investor #{self.id}"


class PMPropertyInvestor(models.Model):
    """
    Link investors to properties (many-to-many).
    """

    ROLE_OWNER = "OWNER"
    ROLE_PARTNER = "PARTNER"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_PARTNER, "Partner"),
    ]

    business_id = models.IntegerField(db_index=True)

    investor = models.ForeignKey(PMInvestor, on_delete=models.CASCADE, related_name="property_links")
    property = models.ForeignKey(PMProperty, on_delete=models.CASCADE, related_name="investor_links")

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OWNER)
    ownership_percent = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = (("investor", "property"),)
        indexes = [
            models.Index(fields=["business_id", "investor"]),
            models.Index(fields=["business_id", "property"]),
        ]

    def __str__(self) -> str:
        return f"Investor {self.investor_id} -> Property {self.property_id}"


class PMInboxThread(models.Model):
    """
    A conversation thread between PM team and an Investor.
    """

    STATUS_OPEN = "OPEN"
    STATUS_CLOSED = "CLOSED"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    business_id = models.IntegerField(db_index=True)

    investor = models.ForeignKey(PMInvestor, on_delete=models.CASCADE, related_name="threads")
    property = models.ForeignKey(PMProperty, null=True, blank=True, on_delete=models.SET_NULL, related_name="threads")

    subject = models.CharField(max_length=180, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pm_inbox_threads_created",
    )

    last_message_at = models.DateTimeField(null=True, blank=True)

    last_viewed_by_pm_at = models.DateTimeField(null=True, blank=True)
    last_viewed_by_investor_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["business_id", "investor"]),
            models.Index(fields=["business_id", "property"]),
            models.Index(fields=["business_id", "status"]),
        ]

    def __str__(self) -> str:
        return f"Thread #{self.id} (Investor {self.investor_id})"


class PMInboxMessage(models.Model):
    """
    Messages inside a thread.
    """

    SENDER_PM = "PM"
    SENDER_INVESTOR = "INVESTOR"
    SENDER_SYSTEM = "SYSTEM"
    SENDER_CHOICES = [
        (SENDER_PM, "PM"),
        (SENDER_INVESTOR, "Investor"),
        (SENDER_SYSTEM, "System"),
    ]

    business_id = models.IntegerField(db_index=True)

    thread = models.ForeignKey(PMInboxThread, on_delete=models.CASCADE, related_name="messages")

    sender_role = models.CharField(max_length=20, choices=SENDER_CHOICES, default=SENDER_PM)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pm_inbox_messages_sent",
    )

    body = models.TextField()

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["business_id", "thread", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Msg #{self.id} Thread #{self.thread_id}"


class PMNotification(models.Model):
    """
    Investor-facing notifications (badge count + quick actions).
    This is separate from your existing platform notifications.
    """

    TYPE_MESSAGE = "MESSAGE"
    TYPE_STATEMENT = "STATEMENT"
    TYPE_ALERT = "ALERT"
    TYPE_SYSTEM = "SYSTEM"

    TYPE_CHOICES = [
        (TYPE_MESSAGE, "Message"),
        (TYPE_STATEMENT, "Statement"),
        (TYPE_ALERT, "Alert"),
        (TYPE_SYSTEM, "System"),
    ]

    business_id = models.IntegerField(db_index=True)

    investor = models.ForeignKey(PMInvestor, on_delete=models.CASCADE, related_name="notifications")

    notif_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_MESSAGE)

    title = models.CharField(max_length=180, blank=True, default="")
    body = models.TextField(blank=True, default="")

    thread = models.ForeignKey(PMInboxThread, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    message = models.ForeignKey(PMInboxMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")

    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["business_id", "investor", "read_at"]),
            models.Index(fields=["business_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Notif #{self.id} Investor {self.investor_id}"
