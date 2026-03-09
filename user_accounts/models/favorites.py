# backend/user_accounts/models/favorites.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class FavoriteBusiness(models.Model):
    """
    Customer saved businesses ("Order Again" / Business Cards).
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_businesses"
    )
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="favorited_by")

    nickname = models.CharField(max_length=80, blank=True, default="")
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "business"], name="uniq_customer_business_favorite")
        ]

    def __str__(self) -> str:
        return f"FavoriteBusiness(customer={self.customer_id}, business={self.business_id})"

    def touch_used(self) -> None:
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])