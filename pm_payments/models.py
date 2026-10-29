from django.db import models


class PMCollectionSetup(models.Model):
    """Configuration only. No bank details, tokens, funds, or live-payment permissions."""
    class Method(models.TextChoices):
        UNCONFIGURED = "UNCONFIGURED", "Not configured"
        STRIPE_CONNECT = "STRIPE_CONNECT", "Connect bank for SyncWorks payments"
        EXTERNAL = "EXTERNAL", "Existing payment processor"
        MANUAL = "MANUAL", "Cash/check/manual tracking"

    business_id = models.PositiveIntegerField(unique=True, db_index=True)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.UNCONFIGURED)
    external_provider_name = models.CharField(max_length=100, blank=True, default="")
    external_provider_url = models.URLField(max_length=500, blank=True, default="")
    trust_account_reviewed_at = models.DateTimeField(null=True, blank=True)
    trust_account_reviewed_by_id = models.PositiveIntegerField(null=True, blank=True)
    updated_by_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"PMCollectionSetup(business_id={self.business_id}, method={self.method})"
