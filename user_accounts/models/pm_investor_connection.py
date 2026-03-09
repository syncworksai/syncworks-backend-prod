# backend/user_accounts/models/pm_investor_connection.py
from __future__ import annotations

import secrets

from django.db import models


class PMInvestorConnection(models.Model):
    """
    Connects an investor to a PM company (Business), using business_id to match your X-Business-Id pattern.
    This is your "friend request" mechanic between PM business and investor.

    Investors can belong to multiple PM companies.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        REVOKED = "REVOKED", "Revoked"

    investor = models.ForeignKey("user_accounts.PMInvestor", on_delete=models.CASCADE, related_name="connections")
    business_id = models.PositiveIntegerField(db_index=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    # PM can create/share this code. Investor can also enter it to connect.
    connect_code = models.CharField(max_length=32, unique=True, db_index=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("investor", "business_id")]

    def ensure_connect_code(self) -> None:
        if self.connect_code:
            return
        self.connect_code = secrets.token_urlsafe(16)[:32]

    def save(self, *args, **kwargs):
        if not self.connect_code:
            self.ensure_connect_code()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"PMInvestorConnection(inv={self.investor_id}, biz={self.business_id}, {self.status})"
