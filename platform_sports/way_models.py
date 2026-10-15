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

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="way_metric_ratings")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="way_metric_ratings")
    metric_key = models.CharField(max_length=32, choices=Metric.choices)
    value = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)])
    period_key = models.CharField(max_length=32, default="CURRENT")
    week_of = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)
    rated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_way_ratings_given")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "metric_key", "period_key")
        constraints = [models.UniqueConstraint(fields=("team", "player", "metric_key", "period_key"), name="sports_unique_way_metric_period")]
        indexes = [models.Index(fields=("team", "period_key"), name="sports_way_rating_period"), models.Index(fields=("player", "metric_key"), name="sports_way_rating_player")]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"player": "Player must belong to this team."})


class SportsTeamWeekMetric(models.Model):
    """Editable weekly expectations layered over calculated team performance."""

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="way_week_metrics")
    week_of = models.DateField()
    expected_runs_per_game = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_way_week_metrics_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("week_of", "id")
        constraints = [models.UniqueConstraint(fields=("team", "week_of"), name="sports_unique_way_team_week")]
        indexes = [models.Index(fields=("team", "week_of"), name="sports_way_team_week")]


class SportsPlayerExecutionTotal(models.Model):
    """Coach-recorded execution points, kept like hits and converted to EXE% by graded PA."""

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="way_execution_totals")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="way_execution_totals")
    season_name = models.CharField(max_length=80, blank=True)
    points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    opportunities = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sports_execution_totals_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "id")
        constraints = [models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_execution_total_season")]
        indexes = [models.Index(fields=("team", "season_name"), name="sports_exec_total_season")]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"player": "Player must belong to this team."})


class SportsPlayerQABTotal(models.Model):
    """Aggregate 1-3 Quality At-Bat points divided by graded QAB opportunities."""

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="way_qab_totals")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="way_qab_totals")
    season_name = models.CharField(max_length=80, blank=True)
    points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sports_qab_totals_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "id")
        constraints = [models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_qab_total_season")]
        indexes = [models.Index(fields=("team", "season_name"), name="sports_qab_total_season")]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"player": "Player must belong to this team."})


class SportsPlayerSituationalSplit(models.Model):
    """Situational six-game splits plus an independent season H/AB snapshot."""

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="way_situational_splits")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="way_situational_splits")
    season_name = models.CharField(max_length=80, blank=True)
    sample_games = models.PositiveSmallIntegerField(default=0)
    bases_empty_hits = models.PositiveIntegerField(default=0)
    bases_empty_ab = models.PositiveIntegerField(default=0)
    two_out_hits = models.PositiveIntegerField(default=0)
    two_out_ab = models.PositiveIntegerField(default=0)
    runners_on_hits = models.PositiveIntegerField(default=0)
    runners_on_ab = models.PositiveIntegerField(default=0)
    batting_sample_games = models.PositiveSmallIntegerField(default=0)
    batting_hits = models.PositiveIntegerField(default=0)
    batting_ab = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sports_situational_splits_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "id")
        constraints = [models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_situational_split_season")]
        indexes = [models.Index(fields=("team", "season_name"), name="sports_situational_season")]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            raise ValidationError({"player": "Player must belong to this team."})
        for hits_field, ab_field, label in (
            ("bases_empty_hits", "bases_empty_ab", "Bases empty"),
            ("two_out_hits", "two_out_ab", "Two outs"),
            ("runners_on_hits", "runners_on_ab", "Runners on"),
            ("batting_hits", "batting_ab", "Season batting"),
        ):
            if getattr(self, hits_field, 0) > getattr(self, ab_field, 0):
                raise ValidationError({hits_field: f"{label} hits cannot exceed at-bats."})
