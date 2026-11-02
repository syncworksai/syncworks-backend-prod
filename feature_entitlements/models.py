from django.conf import settings
from django.db import models
from django.utils import timezone

FEATURES = ("business_jarvis", "ai_assistant", "technician_tracking", "ai_weather", "ai_traffic", "smart_routes", "automated_email", "ai_phone")

class BusinessFeatureEntitlement(models.Model):
    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="feature_entitlements")
    feature = models.CharField(max_length=48, choices=[(f, f) for f in FEATURES])
    state = models.CharField(max_length=16, choices=[("OFF", "Off"), ("TRIAL", "Trial"), ("PAID", "Paid"), ("OVERRIDE", "Admin override")], default="OFF")
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_expires_at = models.DateTimeField(null=True, blank=True)
    paid_through = models.DateTimeField(null=True, blank=True)
    override_expires_at = models.DateTimeField(null=True, blank=True)
    override_reason = models.CharField(max_length=300, blank=True, default="")
    modified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "feature"], name="unique_business_feature_entitlement")]
    def active(self):
        now = timezone.now()
        if self.state == "TRIAL": return bool(self.trial_expires_at and self.trial_expires_at > now)
        if self.state == "PAID": return bool(self.paid_through and self.paid_through > now)
        if self.state == "OVERRIDE": return bool(self.override_reason and self.override_expires_at and self.override_expires_at > now)
        return False

class BusinessAIBudget(models.Model):
    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE, related_name="ai_budgets")
    period = models.CharField(max_length=7)  # UTC YYYY-MM
    reserved_cents = models.PositiveIntegerField(default=0)
    spent_cents = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "period"], name="unique_business_ai_month")]
