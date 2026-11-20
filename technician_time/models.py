from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

class TechnicianShift(models.Model):
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="technician_shifts")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="technician_shifts")
    clock_in_at = models.DateTimeField(default=timezone.now)
    clock_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-clock_in_at"]
        constraints = [
            models.UniqueConstraint(fields=["business", "technician"], condition=Q(clock_out_at__isnull=True), name="one_active_tech_shift_per_business")
        ]

class TechnicianJobEvent(models.Model):
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE)
    ticket = models.ForeignKey("user_accounts.Ticket", on_delete=models.CASCADE, related_name="technician_time_events")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=40)
    note = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]
