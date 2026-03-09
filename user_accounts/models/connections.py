from django.db import models
from django.conf import settings

User = settings.AUTH_USER_MODEL


class Connection(models.Model):
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="connections_sent",
        null=True,
        blank=True,
    )

    addressee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="connections_received",
        null=True,
        blank=True,
    )

    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.requester} → {self.addressee}"
