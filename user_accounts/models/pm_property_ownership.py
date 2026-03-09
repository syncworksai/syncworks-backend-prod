# backend/user_accounts/models/pm_property_ownership.py
from __future__ import annotations

from django.db import models


class PMPropertyOwnership(models.Model):
    """
    v1 single-owner-per-property without modifying PMProperty directly:
    - property is OneToOne -> PMProperty (enforces single owner)
    - owner is FK -> PMInvestor

    This is also where we can store management fee overrides per property later if needed.
    """

    property = models.OneToOneField(
        "user_accounts.PMProperty",
        on_delete=models.CASCADE,
        related_name="ownership",
    )

    investor = models.ForeignKey(
        "user_accounts.PMInvestor",
        on_delete=models.PROTECT,
        related_name="owned_properties",
    )

    # Optional notes (deed info, % ownership later, etc.)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["investor"]),
        ]

    def __str__(self) -> str:
        return f"PMPropertyOwnership(prop={self.property_id}, investor={self.investor_id})"
