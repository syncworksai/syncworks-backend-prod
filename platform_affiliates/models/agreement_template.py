from __future__ import annotations

from django.db import models


class AffiliateAgreementTemplate(models.Model):
    version = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=180, default="SyncWorks Affiliate Agreement")
    body = models.TextField()
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["version"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.version})"