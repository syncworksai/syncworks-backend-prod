"""Recurring PM lead capture subscription, scoped to one owned PM workspace."""
from django.db import models

class PMLeadSubscription(models.Model):
    workspace = models.OneToOneField("pm_workspace.PMWorkspace", on_delete=models.CASCADE, related_name="lead_subscription")
    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    stripe_checkout_session_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=24, default="NONE")
    mailbox_count = models.PositiveSmallIntegerField(default=1)
    features = models.JSONField(default=list, blank=True)
    monthly_cents = models.PositiveIntegerField(default=0)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def is_active(self):
        return self.status in {"ACTIVE", "TRIALING"}
