from __future__ import annotations

from django.conf import settings
from django.db import models


class PersonalIdentity(models.Model):
    """Canonical user-facing identity and privacy choices.

    Authentication identity remains on User. This model stores reusable profile
    information that can be shared across Personal, Social, Marketplace and
    future discovery modules without exposing private location data.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_identity",
    )
    display_name = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    bio = models.CharField(max_length=500, blank=True, default="")
    public_city = models.CharField(max_length=80, blank=True, default="")
    public_state = models.CharField(max_length=32, blank=True, default="")
    profile_photo = models.ImageField(
        upload_to="identity/profile_photos/",
        null=True,
        blank=True,
    )

    show_photo_services = models.BooleanField(default=True)
    show_photo_social = models.BooleanField(default=True)
    show_photo_groups = models.BooleanField(default=True)
    show_city_public = models.BooleanField(default=False)

    use_current_for_weather = models.BooleanField(default=True)
    use_current_for_traffic = models.BooleanField(default=True)
    use_current_for_nearby = models.BooleanField(default=True)
    use_current_for_local_info = models.BooleanField(default=True)

    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"PersonalIdentity(user={self.user_id})"


class UserLocation(models.Model):
    class Kind(models.TextChoices):
        HOME = "HOME", "Home"
        WORK = "WORK", "Work"
        SAVED = "SAVED", "Saved place"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_locations",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SAVED)
    label = models.CharField(max_length=80, blank=True, default="")
    address_line1 = models.CharField(max_length=220)
    address_line2 = models.CharField(max_length=120, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=80, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="US")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default_service = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default_service", "kind", "label", "id"]
        indexes = [
            models.Index(fields=["user", "kind"]),
            models.Index(fields=["user", "is_default_service"]),
        ]

    @property
    def formatted_address(self) -> str:
        city_state = ", ".join([part for part in [self.city, self.state] if part])
        tail = " ".join([part for part in [city_state, self.postal_code] if part])
        return ", ".join([part for part in [self.address_line1, self.address_line2, tail] if part])

    def __str__(self) -> str:
        return f"UserLocation(user={self.user_id}, kind={self.kind}, label={self.label})"


class BusinessVerification(models.Model):
    class Status(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Unverified"
        IN_REVIEW = "IN_REVIEW", "In review"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"

    business = models.OneToOneField(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="verification",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNVERIFIED)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    identity_verified = models.BooleanField(default=False)
    business_details_verified = models.BooleanField(default=False)
    payment_verified = models.BooleanField(default=False)
    license_verified = models.BooleanField(default=False)
    insurance_verified = models.BooleanField(default=False)
    background_verified = models.BooleanField(default=False)
    review_notes = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def public_checks(self) -> dict[str, bool]:
        return {
            "email": self.email_verified,
            "phone": self.phone_verified,
            "identity": self.identity_verified,
            "business_details": self.business_details_verified,
            "payment": self.payment_verified,
            "license": self.license_verified,
            "insurance": self.insurance_verified,
            "background": self.background_verified,
        }

    def __str__(self) -> str:
        return f"BusinessVerification(business={self.business_id}, status={self.status})"
