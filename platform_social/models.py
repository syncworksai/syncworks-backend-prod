from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Connection(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        BLOCKED = "BLOCKED", "Blocked"

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_connections_sent")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_connections_received")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("sender", "recipient"), name="social_unique_connection_direction"),
            models.CheckConstraint(condition=~Q(sender=models.F("recipient")), name="social_no_self_connection"),
        ]
        indexes = [
            models.Index(fields=("sender", "status"), name="social_conn_sender_status"),
            models.Index(fields=("recipient", "status"), name="social_conn_recipient_status"),
        ]

    def clean(self):
        if self.sender_id and self.sender_id == self.recipient_id:
            raise ValidationError("You cannot connect to yourself.")


class SocialGroup(models.Model):
    class Kind(models.TextChoices):
        ORGANIZATION = "ORGANIZATION", "Organization"
        DIVISION = "DIVISION", "Division / Chapter"
        TEAM = "TEAM", "Team"
        CLUB = "CLUB", "Club"
        COMMUNITY = "COMMUNITY", "Community"
        HOUSEHOLD = "HOUSEHOLD", "Household"
        OTHER = "OTHER", "Other"

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"
        PRIVATE = "PRIVATE", "Private"
        INVITE_ONLY = "INVITE_ONLY", "Invite only"

    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.COMMUNITY)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_groups_created")
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    logo_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        indexes = [models.Index(fields=("parent", "is_active"), name="social_group_parent_active")]

    def clean(self):
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "A group cannot be its own parent."})

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        DIRECTOR = "DIRECTOR", "Director"
        MANAGER = "MANAGER", "Manager / Coach"
        MEMBER = "MEMBER", "Member"

    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        DECLINED = "DECLINED", "Declined"
        REMOVED = "REMOVED", "Removed"

    group = models.ForeignKey(SocialGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_group_memberships")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INVITED)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="social_membership_invites_sent")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("group", "user"), name="social_unique_group_member")]
        indexes = [models.Index(fields=("group", "status", "role"), name="social_group_member_lookup")]


class SocialEvent(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    organizer_group = models.ForeignKey(SocialGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_events_created")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="America/Chicago")
    venue_name = models.CharField(max_length=180, blank=True)
    address_line1 = models.CharField(max_length=220, blank=True)
    address_line2 = models.CharField(max_length=220, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="US")
    entry_amount_cents = models.PositiveIntegerField(default=0)
    payment_due_at = models.DateTimeField(null=True, blank=True)
    prizes = models.TextField(blank=True)
    rules = models.TextField(blank=True)
    flyer_url = models.URLField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("start_at", "id")
        indexes = [models.Index(fields=("organizer_group", "status", "start_at"), name="social_event_group_start")]

    def clean(self):
        if self.end_at and self.end_at < self.start_at:
            raise ValidationError({"end_at": "End time cannot be before start time."})


class GroupEventInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    event = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name="group_invitations")
    target_group = models.ForeignKey(SocialGroup, on_delete=models.CASCADE, related_name="event_invitations")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_event_invites_sent")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="social_event_invites_responded")
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("event", "target_group"), name="social_unique_event_group_invite")]
        indexes = [models.Index(fields=("target_group", "status"), name="social_event_invite_status")]


class EventMemberResponse(models.Model):
    class Response(models.TextChoices):
        PENDING = "PENDING", "Pending"
        YES = "YES", "Yes"
        MAYBE = "MAYBE", "Maybe"
        NO = "NO", "No"

    event = models.ForeignKey(SocialEvent, on_delete=models.CASCADE, related_name="member_responses")
    group = models.ForeignKey(SocialGroup, on_delete=models.CASCADE, related_name="event_member_responses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_event_responses")
    response = models.CharField(max_length=10, choices=Response.choices, default=Response.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("event", "group", "user"), name="social_unique_member_event_response")]
        indexes = [models.Index(fields=("event", "group", "response"), name="social_event_response_lookup")]


class Collection(models.Model):
    class SplitMethod(models.TextChoices):
        EQUAL = "EQUAL", "Equal"
        CUSTOM = "CUSTOM", "Custom"
        QUANTITY = "QUANTITY", "Quantity based"
        OPTIONAL = "OPTIONAL", "Optional contribution"
        REQUIRED = "REQUIRED", "Required contribution"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        FUNDED = "FUNDED", "Funded"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    group = models.ForeignKey(SocialGroup, on_delete=models.CASCADE, related_name="collections")
    event = models.ForeignKey(SocialEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="collections")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_collections_created")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    total_amount_cents = models.PositiveIntegerField(default=0)
    split_method = models.CharField(max_length=12, choices=SplitMethod.choices, default=SplitMethod.EQUAL)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    platform_fee_bps = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("group", "status"), name="social_collection_status")]


class CollectionShare(models.Model):
    class Status(models.TextChoices):
        DUE = "DUE", "Due"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"
        WAIVED = "WAIVED", "Waived"

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_collection_shares")
    amount_due_cents = models.PositiveIntegerField(default=0)
    amount_paid_cents = models.PositiveIntegerField(default=0)
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DUE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("collection", "user"), name="social_unique_collection_share")]
        indexes = [models.Index(fields=("collection", "status"), name="social_share_status")]


# Imported here so Django registers the shared communication model with this app.
from .communication_models import SocialMessage  # noqa: E402,F401
