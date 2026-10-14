from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SportsPlayerMetricRating(models.Model):
    """Coach-entered 1-10 ratings kept separate from official Game Book math."""

    class Metric(models.TextChoices):
        PLAYER_GRADE = "PLAYER_GRADE", "Coach Grade"
        PLATE_APPROACH = "PLATE_APPROACH", "Plate Approach"
        EXECUTION = "EXECUTION", "Execution"

    team = models.ForeignKey(
        "platform_sports.SportsTeam",
        on_delete=models.CASCADE,
        related_name="way_metric_ratings",
    )
    player = models.ForeignKey(
        "platform_sports.SportsPlayer",
        on_delete=models.CASCADE,
        related_name="way_metric_ratings",
    )
    metric_key = models.CharField(max_length=32, choices=Metric.choices)
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    period_key = models.CharField(max_length=32, default="CURRENT")
    week_of = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)
    rated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sports_way_ratings_given",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "metric_key", "period_key")
        constraints = [
            models.UniqueConstraint(
                fields=("team", "player", "metric_key", "period_key"),
                name="sports_unique_way_metric_period",
            )
        ]
        indexes = [
            models.Index(fields=("team", "period_key"), name="sports_way_rating_period"),
            models.Index(fields=("player", "metric_key"), name="sports_way_rating_player"),
        ]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"player": "Player must belong to this team."})


class SportsTeamWeekMetric(models.Model):
    """Editable weekly expectations layered over calculated team performance."""

    team = models.ForeignKey(
        "platform_sports.SportsTeam",
        on_delete=models.CASCADE,
        related_name="way_week_metrics",
    )
    week_of = models.DateField()
    expected_runs_per_game = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sports_way_week_metrics_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("week_of", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("team", "week_of"),
                name="sports_unique_way_team_week",
            )
        ]
        indexes = [models.Index(fields=("team", "week_of"), name="sports_way_team_week")]
