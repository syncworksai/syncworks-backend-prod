from django.conf import settings
from django.db import models


class JarvisProfile(models.Model):
    class Plan(models.TextChoices):
        BASIC = "BASIC", "Basic"
        PERSONAL = "PERSONAL", "Personal AI"
        FAMILY = "FAMILY", "Family"
        EXECUTIVE = "EXECUTIVE", "Executive"

    class Status(models.TextChoices):
        FREE = "FREE", "Free"
        TRIALING = "TRIALING", "Trialing"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past due"
        CANCELLED = "CANCELLED", "Cancelled"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_profile")
    assistant_name = models.CharField(max_length=40, default="SYNC")
    tone = models.CharField(max_length=24, default="CALM")
    briefing_length = models.CharField(max_length=24, default="STANDARD")
    template = models.CharField(max_length=32, default="GENERAL")
    wake_time = models.TimeField(null=True, blank=True)
    bedtime = models.TimeField(null=True, blank=True)
    quiet_hours_enabled = models.BooleanField(default=False)
    goals = models.JSONField(default=list, blank=True)
    modules = models.JSONField(default=dict, blank=True)
    permissions = models.JSONField(default=dict, blank=True)
    onboarding_step = models.PositiveSmallIntegerField(default=0)
    onboarding_complete = models.BooleanField(default=False)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.BASIC)
    subscription_status = models.CharField(max_length=20, choices=Status.choices, default=Status.FREE)
    stripe_price_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class JarvisDaySession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_day_sessions")
    local_date = models.DateField()
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    check_out_reason = models.CharField(max_length=40, blank=True, default="")
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "local_date"), name="jarvis_unique_user_day")]
        ordering = ("-local_date",)
