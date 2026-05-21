from __future__ import annotations

from django.conf import settings
from django.db import models


class AffiliateAuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="affiliate_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    business = models.ForeignKey(
        "user_accounts.Business",
        related_name="affiliate_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    action = models.CharField(max_length=120)
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["affiliate", "created_at"]),
            models.Index(fields=["business", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at}"