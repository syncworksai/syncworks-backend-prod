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


class PaymentMigrationPlan(models.Model):
    """Shared Business/PM onboarding journey; no charge, payout or bank details.

    Owner-attested progress is distinguished from founder-reviewed payment test
    evidence. Neither is a processor settlement or permission to go live.
    """
    business = models.OneToOneField(
        "user_accounts.Business", on_delete=models.CASCADE, related_name="payment_migration"
    )
    workspace_reviewed_at = models.DateTimeField(null=True, blank=True)
    current_processor = models.CharField(max_length=100, blank=True, default="")
    current_monthly_fees = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_monthly_transactions = models.PositiveIntegerField(null=True, blank=True)
    average_payout_days = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    monthly_reconciliation_hours = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    costs_reviewed_at = models.DateTimeField(null=True, blank=True)
    test_evidence = models.JSONField(default=dict, blank=True)
    test_notes = models.TextField(blank=True, default="")
    test_review_requested_at = models.DateTimeField(null=True, blank=True)
    founder_test_reviewed_at = models.DateTimeField(null=True, blank=True)
    founder_test_reviewer_id = models.PositiveIntegerField(null=True, blank=True)
    founder_test_notes = models.TextField(blank=True, default="")
    switch_requested_at = models.DateTimeField(null=True, blank=True)
    updated_by_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
