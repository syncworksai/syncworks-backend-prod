from __future__ import annotations

from django.conf import settings
from django.db import models


class PlatformUserClassification(models.Model):
    class Kind(models.TextChoices):
        UNCLASSIFIED = "UNCLASSIFIED", "Unclassified"
        REAL_USER = "REAL_USER", "Real user"
        TEST_ACCOUNT = "TEST_ACCOUNT", "Test account"
        BETA_TESTER = "BETA_TESTER", "Beta tester"
        INTERNAL = "INTERNAL", "Internal"
        DEMO = "DEMO", "Demo"
        BILLING_RESTRICTED = "BILLING_RESTRICTED", "Billing restricted"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_classification",
    )
    kind = models.CharField(
        max_length=32,
        choices=Kind.choices,
        default=Kind.UNCLASSIFIED,
        db_index=True,
    )
    note = models.TextField(blank=True)
    intelligence = models.JSONField(
        default=dict,
        blank=True,
        help_text="God Mode attribution, access, acquisition, customer and revenue metadata.",
    )
    classified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_user_classifications_made",
    )
    classified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"{self.user_id}: {self.kind}"
