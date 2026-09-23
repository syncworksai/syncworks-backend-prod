from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from platform_social.models import SocialEvent, SocialGroup


class SportsTeam(models.Model):
    class Sport(models.TextChoices):
        SOFTBALL = "SOFTBALL", "Softball"
        BASEBALL = "BASEBALL", "Baseball"
        BASKETBALL = "BASKETBALL", "Basketball"
        SOCCER = "SOCCER", "Soccer"
        FOOTBALL = "FOOTBALL", "Football"
        VOLLEYBALL = "VOLLEYBALL", "Volleyball"
        OTHER = "OTHER", "Other"

    group = models.OneToOneField(
        SocialGroup,
        on_delete=models.CASCADE,
        related_name="sports_team",
    )
    sport = models.CharField(max_length=20, choices=Sport.choices, default=Sport.SOFTBALL)
    season_name = models.CharField(max_length=120, blank=True)
    league_name = models.CharField(max_length=180, blank=True)
    division_name = models.CharField(max_length=120, blank=True)
    badge_rules = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_teams_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("group__name", "id")

    def clean(self):
        if self.group_id and self.group.kind != SocialGroup.Kind.TEAM:
            raise ValidationError({"group": "Sports teams must use a Social group with kind TEAM."})

    def __str__(self):
        return f"{self.group.name} · {self.get_sport_display()}"


class SportsPlayer(models.Model):
    class Hand(models.TextChoices):
        LEFT = "L", "Left"
        RIGHT = "R", "Right"
        SWITCH = "S", "Switch"
        UNKNOWN = "", "Not set"

    team = models.ForeignKey(SportsTeam, on_delete=models.CASCADE, related_name="players")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_player_profiles",
    )
    display_name = models.CharField(max_length=180)
    jersey_number = models.CharField(max_length=12, blank=True)
    bats = models.CharField(max_length=1, choices=Hand.choices, blank=True, default="")
    throws = models.CharField(max_length=1, choices=Hand.choices, blank=True, default="")
    primary_position = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_player_records")
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_players_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "display_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("team", "user"),
                condition=Q(user__isnull=False),
                name="sports_unique_team_user",
            )
        ]
        indexes = [models.Index(fields=("team", "is_active"), name="sports_player_active")]

    def __str__(self):
        return self.display_name


class SportsGame(models.Model):
    class GameType(models.TextChoices):
        LEAGUE = "LEAGUE", "League"
        TOURNAMENT = "TOURNAMENT", "Tournament"
        PRACTICE = "PRACTICE", "Practice"
        EXHIBITION = "EXHIBITION", "Exhibition"

    class HomeAway(models.TextChoices):
        HOME = "HOME", "Home"
        AWAY = "AWAY", "Away"
        NEUTRAL = "NEUTRAL", "Neutral"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        LIVE = "LIVE", "Live"
        FINAL = "FINAL", "Final"
        CANCELLED = "CANCELLED", "Cancelled"

    team = models.ForeignKey(SportsTeam, on_delete=models.CASCADE, related_name="games")
    social_event = models.OneToOneField(
        SocialEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_game",
    )
    game_type = models.CharField(max_length=16, choices=GameType.choices, default=GameType.LEAGUE)
    opponent_name = models.CharField(max_length=180)
    tournament_name = models.CharField(max_length=180, blank=True)
    round_label = models.CharField(max_length=120, blank=True)
    home_away = models.CharField(max_length=10, choices=HomeAway.choices, default=HomeAway.NEUTRAL)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="America/Chicago")
    venue_name = models.CharField(max_length=180, blank=True)
    address_line1 = models.CharField(max_length=220, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    innings_scheduled = models.PositiveSmallIntegerField(default=7)
    rule_set = models.ForeignKey(
        "platform_sports.SoftballRuleSet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="games",
    )
    home_runs_against = models.PositiveSmallIntegerField(default=0)
    gamecast_enabled = models.BooleanField(default=False)
    fan_gamecast_notified_at = models.DateTimeField(null=True, blank=True)
    gamecast_token = models.UUIDField(default=uuid.uuid4, editable=False)
    gamecast_show_batter = models.BooleanField(default=True)
    gamecast_show_recent_plays = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    current_inning = models.PositiveSmallIntegerField(default=1)
    outs = models.PositiveSmallIntegerField(default=0)
    current_batter_order = models.PositiveSmallIntegerField(default=1)
    runs_for = models.PositiveSmallIntegerField(default=0)
    runs_against = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_games_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("start_at", "id")
        indexes = [models.Index(fields=("team", "status", "start_at"), name="sports_game_lookup")]

    def clean(self):
        if self.end_at and self.end_at < self.start_at:
            raise ValidationError({"end_at": "End time cannot be before start time."})
        if self.outs > 2:
            raise ValidationError({"outs": "Live outs must be between 0 and 2."})

    def __str__(self):
        return f"{self.team.group.name} vs {self.opponent_name}"


class SportsScorebookPage(models.Model):
    """Private, durable scan of one side of a physical game book."""

    class Side(models.TextChoices):
        TEAM = "TEAM", "Our team"
        OPPONENT = "OPPONENT", "Opponent"

    game = models.ForeignKey(
        SportsGame, on_delete=models.CASCADE, related_name="scorebook_pages",
    )
    side = models.CharField(max_length=12, choices=Side.choices)
    page_order = models.PositiveSmallIntegerField(default=1)
    filename = models.CharField(max_length=160, blank=True)
    source_sha256 = models.CharField(max_length=64)
    image_mime = models.CharField(max_length=32, default="image/jpeg")
    image_data = models.BinaryField(repr=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="sports_scorebook_uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("page_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("game", "source_sha256"),
                name="sports_unique_scorebook_scan",
            ),
        ]


class SportsScorebookReview(models.Model):
    """Draft transcription never touches player statistics until approved."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Needs review"
        SCORE_VERIFIED = "SCORE_VERIFIED", "Final score verified"
        FULLY_VERIFIED = "FULLY_VERIFIED", "All plays verified"

    game = models.OneToOneField(
        SportsGame, on_delete=models.CASCADE, related_name="scorebook_review",
    )
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT,
    )
    applied_sha256 = models.CharField(max_length=64, blank=True)
    audit_log = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="sports_scorebook_reviews",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sports_scorebooks_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class SportsLineupSpot(models.Model):
    game = models.ForeignKey(SportsGame, on_delete=models.CASCADE, related_name="lineup_spots")
    player = models.ForeignKey(SportsPlayer, on_delete=models.CASCADE, related_name="lineup_spots")
    batting_order = models.PositiveSmallIntegerField()
    defensive_position = models.CharField(max_length=40, blank=True)
    is_starter = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("batting_order", "id")
        constraints = [
            models.UniqueConstraint(fields=("game", "batting_order"), name="sports_unique_bat_order"),
            models.UniqueConstraint(fields=("game", "player"), name="sports_unique_game_player"),
        ]

    def clean(self):
        if self.game_id and self.player_id and self.player.team_id != self.game.team_id:
            raise ValidationError({"player": "Lineup player must belong to the game's team."})

    def __str__(self):
        return f"{self.batting_order}. {self.player.display_name}"


class SportsSubstitution(models.Model):
    game = models.ForeignKey(SportsGame, on_delete=models.CASCADE, related_name="substitutions")
    outgoing_player = models.ForeignKey(
        SportsPlayer, on_delete=models.PROTECT, related_name="substitutions_out"
    )
    incoming_player = models.ForeignKey(
        SportsPlayer, on_delete=models.PROTECT, related_name="substitutions_in"
    )
    batting_order = models.PositiveSmallIntegerField()
    defensive_position = models.CharField(max_length=40, blank=True)
    inning = models.PositiveSmallIntegerField(default=1)
    note = models.CharField(max_length=180, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_substitutions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("game", "batting_order"), name="sports_sub_game_order"),
        ]

    def clean(self):
        if self.outgoing_player_id == self.incoming_player_id:
            raise ValidationError("Substitute must be a different player.")
        if self.game_id:
            if self.outgoing_player.team_id != self.game.team_id or self.incoming_player.team_id != self.game.team_id:
                raise ValidationError("Both substitution players must belong to the game team.")


class SportsGameInning(models.Model):
    game = models.ForeignKey(SportsGame, on_delete=models.CASCADE, related_name="inning_lines")
    inning = models.PositiveSmallIntegerField()
    team_runs = models.PositiveSmallIntegerField(default=0)
    opponent_runs = models.PositiveSmallIntegerField(default=0)
    opponent_hits = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("inning", "id")
        constraints = [
            models.UniqueConstraint(fields=("game", "inning"), name="sports_unique_game_inning"),
        ]

    def __str__(self):
        return f"{self.game_id} · inning {self.inning}"


class SoftballPlateAppearance(models.Model):
    class Result(models.TextChoices):
        SINGLE = "1B", "Single"
        DOUBLE = "2B", "Double"
        TRIPLE = "3B", "Triple"
        HOME_RUN = "HR", "Home run"
        WALK = "BB", "Walk"
        OUT = "OUT", "Out"
        STRIKEOUT = "K", "Strikeout"
        REACHED_ON_ERROR = "ROE", "Reached on error"
        FIELDERS_CHOICE = "FC", "Fielder's choice"
        SAC_FLY = "SF", "Sacrifice fly"

    game = models.ForeignKey(SportsGame, on_delete=models.CASCADE, related_name="plate_appearances")
    player = models.ForeignKey(SportsPlayer, on_delete=models.PROTECT, related_name="plate_appearances")
    sequence = models.PositiveIntegerField()
    inning = models.PositiveSmallIntegerField(default=1)
    result = models.CharField(max_length=4, choices=Result.choices)
    outs_recorded = models.PositiveSmallIntegerField(default=0)
    rbi = models.PositiveSmallIntegerField(default=0)
    runs_scored = models.PositiveSmallIntegerField(default=0)
    notes = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="softball_plate_appearances_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence", "id")
        constraints = [models.UniqueConstraint(fields=("game", "sequence"), name="sports_unique_pa_sequence")]
        indexes = [models.Index(fields=("game", "player"), name="sports_pa_game_player")]

    def clean(self):
        if self.game_id and self.player_id and self.player.team_id != self.game.team_id:
            raise ValidationError({"player": "Plate appearance player must belong to the game's team."})
        if self.outs_recorded > 3:
            raise ValidationError({"outs_recorded": "Outs recorded cannot exceed 3."})

    def __str__(self):
        return f"{self.game_id} · {self.sequence} · {self.player.display_name} · {self.result}"
