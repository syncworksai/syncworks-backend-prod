from __future__ import annotations

from django.conf import settings
from django.db import models


class ProductionReadinessState(models.Model):
    """Durable God Mode signoff for production release gates.

    Runtime checks are recalculated on every audit request. This model stores only
    external/provider verification and end-to-end certification decisions that the
    application cannot truthfully infer on its own.
    """

    key = models.CharField(max_length=32, unique=True, default="GLOBAL")
    external_verification = models.JSONField(default=dict, blank=True)
    certification = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="production_readiness_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"Production readiness: {self.key}"
