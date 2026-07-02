from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


def _partner_invitation_token() -> str:
    return secrets.token_urlsafe(32)


class BusinessPartnerRelationship(models.Model):
    class RelationshipType(models.TextChoices):
        SUBCONTRACTOR = "SUBCONTRACTOR", "Subcontractor"
        VENDOR = "VENDOR", "Vendor"
        REFERRAL = "REFERRAL", "Referral partner"
        JOINT_VENTURE = "JOINT_VENTURE", "Joint venture"
        OVERFLOW = "OVERFLOW", "Overflow provider"
        PREFERRED = "PREFERRED", "Preferred service partner"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DECLINED = "DECLINED", "Declined"
        TERMINATED = "TERMINATED", "Terminated"

    class MarkupType(models.TextChoices):
        NONE = "NONE", "No default markup"
        PERCENTAGE = "PERCENTAGE", "Percentage"
        FIXED = "FIXED", "Fixed amount"

    hiring_business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="partner_relationships_outbound",
    )
    partner_business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="partner_relationships_inbound",
    )
    relationship_type = models.CharField(
        max_length=24,
        choices=RelationshipType.choices,
        default=RelationshipType.SUBCONTRACTOR,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    preferred_partner = models.BooleanField(default=False)

    services_allowed = models.ManyToManyField(
        "user_accounts.ServiceCategory",
        blank=True,
        related_name="partner_relationships",
    )
    default_markup_type = models.CharField(
        max_length=20,
        choices=MarkupType.choices,
        default=MarkupType.NONE,
    )
    default_markup_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    payment_terms_days = models.PositiveIntegerField(default=30)

    insurance_verified = models.BooleanField(default=False)
    license_verified = models.BooleanField(default=False)
    compliance_notes = models.TextField(blank=True, default="")
    internal_notes = models.TextField(blank=True, default="")

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_relationships_invited",
        null=True,
        blank=True,
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_relationships_accepted",
        null=True,
        blank=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["hiring_business", "partner_business"],
                name="ua_unique_business_partner_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    hiring_business=models.F("partner_business")
                ),
                name="ua_partner_not_self",
            ),
        ]
        indexes = [
            models.Index(
                fields=["hiring_business", "status", "updated_at"],
                name="ua_partner_out_status_idx",
            ),
            models.Index(
                fields=["partner_business", "status", "updated_at"],
                name="ua_partner_in_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.hiring_business_id} -> "
            f"{self.partner_business_id} ({self.status})"
        )


class BusinessPartnerInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    inviting_business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="partner_invitations_sent",
    )
    target_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        related_name="partner_invitations_received",
        null=True,
        blank=True,
    )
    relationship = models.OneToOneField(
        BusinessPartnerRelationship,
        on_delete=models.SET_NULL,
        related_name="invitation",
        null=True,
        blank=True,
    )

    contact_name = models.CharField(max_length=180, blank=True, default="")
    email = models.EmailField(blank=True, default="", db_index=True)
    phone = models.CharField(max_length=32, blank=True, default="")
    business_name = models.CharField(max_length=180, blank=True, default="")
    relationship_type = models.CharField(
        max_length=24,
        choices=BusinessPartnerRelationship.RelationshipType.choices,
        default=BusinessPartnerRelationship.RelationshipType.SUBCONTRACTOR,
    )
    message = models.TextField(blank=True, default="")
    token = models.CharField(
        max_length=96,
        unique=True,
        default=_partner_invitation_token,
        editable=False,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    affiliate_code = models.CharField(max_length=32, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="partner_invitations_created",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["inviting_business", "status", "created_at"],
                name="ua_partner_invite_sent_idx",
            ),
            models.Index(
                fields=["target_business", "status", "created_at"],
                name="ua_partner_invite_recv_idx",
            ),
            models.Index(
                fields=["email", "status", "created_at"],
                name="ua_partner_invite_email_idx",
            ),
        ]

    def __str__(self) -> str:
        target = self.target_business_id or self.email or self.business_name
        return f"{self.inviting_business_id} -> {target} ({self.status})"
