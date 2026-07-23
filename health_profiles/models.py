from django.conf import settings
from django.db import models


class HealthAthleteProfile(models.Model):
    class AgeGroup(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        CHILD = "child", "Child"
        TEEN = "teen", "Teen"
        YOUNG_ADULT = "young_adult", "Young adult"
        ADULT = "adult", "Adult"
        MASTERS = "masters", "Masters"
        OLDER_ADULT = "older_adult", "Older adult"

    class Experience(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="health_athlete_profile",
    )
    date_of_birth = models.DateField(blank=True, null=True)
    age_group = models.CharField(max_length=24, choices=AgeGroup.choices, default=AgeGroup.UNKNOWN)
    primary_sport = models.CharField(max_length=120, default="General Fitness")
    training_experience = models.CharField(max_length=24, choices=Experience.choices, default=Experience.BEGINNER)
    measurements = models.JSONField(default=dict, blank=True)
    plan_preferences = models.JSONField(default=dict, blank=True)
    simulation_preferences = models.JSONField(default=dict, blank=True)
    requires_plan_review = models.BooleanField(default=False)
    profile_version = models.PositiveIntegerField(default=1)
    last_plan_reset_at = models.DateTimeField(blank=True, null=True)
    last_plan_restart_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"Health profile for {self.user_id}"
