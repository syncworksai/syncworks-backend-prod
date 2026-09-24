from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SportsPlayerProfile(models.Model):
    player = models.OneToOneField(
        "platform_sports.SportsPlayer",
        on_delete=models.CASCADE,
        related_name="manager_profile",
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    show_age_to_team = models.BooleanField(default=False)
    profile_photo = models.ImageField(upload_to="sports/player_profiles/%Y/%m/", blank=True, null=True)
    # Unlike MEDIA_ROOT on ephemeral web instances, compressed card photos stay
    # durable in Postgres and appear consistently on all app servers.
    card_photo_data = models.BinaryField(null=True, blank=True, editable=False)
    card_photo_mime = models.CharField(max_length=32, blank=True, default="")
    card_style = models.CharField(max_length=24, default="CLASSIC", choices=(
        ("CLASSIC", "Classic Gold"),
        ("NEON", "Neon Night"),
        ("DIAMOND", "Diamond"),
        ("MIDNIGHT", "Midnight"),
    ))
    card_nickname = models.CharField(max_length=48, blank=True, default="")
    card_photo_position = models.PositiveSmallIntegerField(default=50)

    emergency_contact_name = models.CharField(max_length=180, blank=True)
    emergency_contact_phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "id")

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile · {self.player}"


class TeamPaymentSettings(models.Model):
    team = models.OneToOneField(
        "platform_sports.SportsTeam",
        on_delete=models.CASCADE,
        related_name="payment_settings",
    )
    cash_app_url = models.URLField(blank=True)
    venmo_url = models.URLField(blank=True)
    stripe_url = models.URLField(blank=True)
    payment_note = models.CharField(max_length=240, blank=True)
    platform_fee_bps = models.PositiveSmallIntegerField(default=100)
    free_mode = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payments · {self.team}"


class TeamFee(models.Model):
    team = models.ForeignKey(
        "platform_sports.SportsTeam",
        on_delete=models.CASCADE,
        related_name="fees",
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    amount_cents = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_team_fees_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("due_date", "title", "id")
        indexes = [models.Index(fields=("team", "is_active"), name="sports_fee_team_active")]

    def __str__(self):
        return f"{self.team} · {self.title}"


class TeamFeeAssignment(models.Model):
    class Status(models.TextChoices):
        DUE = "DUE", "Due"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"
        WAIVED = "WAIVED", "Waived"

    fee = models.ForeignKey(TeamFee, on_delete=models.CASCADE, related_name="assignments")
    player = models.ForeignKey(
        "platform_sports.SportsPlayer",
        on_delete=models.CASCADE,
        related_name="fee_assignments",
    )
    amount_cents = models.PositiveIntegerField(default=0)
    amount_paid_cents = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DUE)
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_fee_assignments_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("fee__due_date", "player__display_name", "id")
        constraints = [
            models.UniqueConstraint(fields=("fee", "player"), name="sports_unique_fee_player")
        ]
        indexes = [models.Index(fields=("player", "status"), name="sports_fee_player_status")]

    def clean(self):
        if self.player_id and self.fee_id and self.player.team_id != self.fee.team_id:
            raise ValidationError({"player": "Player must belong to the fee's team."})

    def save(self, *args, **kwargs):
        if self.fee_id and not self.amount_cents:
            self.amount_cents = self.fee.amount_cents
        if self.status == self.Status.PAID:
            if not self.amount_paid_cents:
                self.amount_paid_cents = self.amount_cents
            self.paid_at = self.paid_at or timezone.now()
        elif self.status in (self.Status.DUE, self.Status.PARTIAL):
            self.paid_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} · {self.fee.title} · {self.status}"


class SoftballStatLedgerEntry(models.Model):
    class Scope(models.TextChoices):
        LEAGUE = "LEAGUE", "League"
        TOURNAMENT = "TOURNAMENT", "Tournament"
        OTHER = "OTHER", "Other"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        IMPORT = "IMPORT", "Import"
        CORRECTION = "CORRECTION", "Correction"

    team = models.ForeignKey(
        "platform_sports.SportsTeam",
        on_delete=models.CASCADE,
        related_name="stat_ledger_entries",
    )
    player = models.ForeignKey(
        "platform_sports.SportsPlayer",
        on_delete=models.CASCADE,
        related_name="stat_ledger_entries",
    )
    season_name = models.CharField(max_length=120, blank=True)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.LEAGUE)
    games = models.PositiveIntegerField(default=0)
    pa = models.PositiveIntegerField(default=0)
    ab = models.PositiveIntegerField(default=0)
    hits = models.PositiveIntegerField(default=0)
    doubles = models.PositiveIntegerField(default=0)
    triples = models.PositiveIntegerField(default=0)
    home_runs = models.PositiveIntegerField(default=0)
    walks = models.PositiveIntegerField(default=0)
    sac_flies = models.PositiveIntegerField(default=0)
    rbi = models.PositiveIntegerField(default=0)
    runs = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="softball_stat_ledger_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__display_name", "scope", "id")
        indexes = [models.Index(fields=("team", "scope"), name="sports_stat_team_scope")]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            raise ValidationError({"player": "Player must belong to this team."})
        if self.hits > self.ab:
            raise ValidationError({"hits": "Hits cannot exceed at-bats."})
        if self.doubles + self.triples + self.home_runs > self.hits:
            raise ValidationError("Extra-base hits cannot exceed total hits.")

    def __str__(self):
        return f"{self.player} · {self.scope} · {self.season_name or 'stats'}"



class SportsPlayerInvite(models.Model):
    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACCEPTED = "ACCEPTED", "Accepted"
        REVOKED = "REVOKED", "Revoked"

    player = models.ForeignKey(
        "platform_sports.SportsPlayer",
        on_delete=models.CASCADE,
        related_name="account_invites",
    )
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INVITED)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_player_invites_sent",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_player_invites_accepted",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("player", "status"), name="sports_player_invite_state"),
            models.Index(fields=("email", "status"), name="sports_player_invite_email"),
        ]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} · {self.email} · {self.status}"


class SportsPlayerMoment(models.Model):
    """Auditable, staff-verified moments for achievements not inferable from an AB."""
    class Kind(models.TextChoices):
        EXTRA_BASE = "EXTRA_BASE", "Took an extra base"
        STEAL = "STEAL", "Successful steal (where permitted)"
        TYING_HIT = "TYING_HIT", "Late tying hit"
        GO_AHEAD_HIT = "GO_AHEAD_HIT", "Late go-ahead hit"

    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.PROTECT, related_name="verified_moments")
    game = models.ForeignKey("platform_sports.SportsGame", on_delete=models.PROTECT, related_name="verified_player_moments")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    plate_appearance = models.ForeignKey("platform_sports.SoftballPlateAppearance", null=True, blank=True, on_delete=models.PROTECT, related_name="verified_moments")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_moments_verified")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-game__start_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("game", "player", "kind"), name="sports_one_verified_kind_per_game"),
        ]
        indexes = [
            models.Index(fields=("player", "kind"), name="sports_moment_player_kind"),
        ]


class SportsPlayerAward(models.Model):
    class Kind(models.TextChoices):
        PLAYER_OF_WEEK = "PLAYER_OF_WEEK", "Player of the Week"
        ROOKIE_OF_YEAR = "ROOKIE_OF_YEAR", "Rookie of the Year"
        GOLD_GLOVE = "GOLD_GLOVE", "Gold Glove"
        HUSTLE = "HUSTLE", "Hustle Award"
        TEAM_FIRST = "TEAM_FIRST", "Team First"
        MVP = "MVP", "Most Valuable Player"
        CUSTOM = "CUSTOM", "Custom"

    team = models.ForeignKey(
        "platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="player_awards"
    )
    player = models.ForeignKey(
        "platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="coach_awards"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.CUSTOM)
    title = models.CharField(max_length=120)
    season_name = models.CharField(max_length=120, blank=True)
    week_of = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    awarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_awards_given"
    )
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-awarded_at", "-id")
        indexes = [
            models.Index(fields=("team", "season_name"), name="sports_award_team_season"),
            models.Index(fields=("player", "kind"), name="sports_award_player_kind"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("team", "player", "kind", "season_name", "week_of"),
                name="sports_unique_player_award_period",
            )
        ]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            raise ValidationError({"player": "Player must belong to the award team."})

    def __str__(self):
        return f"{self.player} · {self.title}"


class SportsPracticeSession(models.Model):
    class Kind(models.TextChoices):
        BATTING_PRACTICE = "BP", "Batting practice"
        SITUATIONS = "SITUATIONS", "Situations"
        FIELDING = "FIELDING", "Fielding"
        TRAINING = "TRAINING", "Training"

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="practice_sessions")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.CASCADE, related_name="practice_sessions")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.BATTING_PRACTICE)
    practiced_at = models.DateTimeField(default=timezone.now)
    title = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_practice_sessions_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-practiced_at", "-id")
        indexes = [
            models.Index(fields=("team", "practiced_at"), name="sports_practice_team_date"),
            models.Index(fields=("player", "practiced_at"), name="sports_practice_player_date"),
        ]

    def clean(self):
        if self.player_id and self.team_id and self.player.team_id != self.team_id:
            raise ValidationError({"player": "Practice player must belong to this team."})

    def __str__(self):
        return f"{self.player} · {self.get_kind_display()} · {self.practiced_at:%Y-%m-%d}"


class SportsPracticeRep(models.Model):
    class Result(models.TextChoices):
        SINGLE = "1B", "Single"
        DOUBLE = "2B", "Double"
        TRIPLE = "3B", "Triple"
        HOME_RUN = "HR", "Home run"
        WALK = "BB", "Walk"
        OUT = "OUT", "Out"
        STRIKEOUT = "K", "Strikeout"
        ERROR = "ROE", "Reached on error"
        FIELDERS_CHOICE = "FC", "Fielder's choice"
        SAC_FLY = "SF", "Sacrifice fly"

    class Objective(models.TextChoices):
        QUALITY_AB = "QUALITY_AB", "Quality at-bat"
        ADVANCE_RUNNER = "ADVANCE_RUNNER", "Move the runner"
        SAC_FLY = "SAC_FLY", "Sacrifice fly"
        SCORE_RUNNER = "SCORE_RUNNER", "Score the runner"
        TWO_OUT_HIT = "TWO_OUT_HIT", "Two-out hitting"
        HIT_BEHIND_RUNNER = "HIT_BEHIND_RUNNER", "Hit behind runner"

    session = models.ForeignKey(SportsPracticeSession, on_delete=models.CASCADE, related_name="reps")
    sequence = models.PositiveIntegerField()
    outs_before = models.PositiveSmallIntegerField(default=0)
    base_state = models.CharField(max_length=8, blank=True, default="")
    objective = models.CharField(max_length=24, choices=Objective.choices, default=Objective.QUALITY_AB)
    result = models.CharField(max_length=4, choices=Result.choices)
    runners_advanced = models.PositiveSmallIntegerField(default=0)
    rbi = models.PositiveSmallIntegerField(default=0)
    successful = models.BooleanField(default=False)
    notes = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(fields=("session", "sequence"), name="sports_unique_practice_rep_seq"),
        ]
        indexes = [
            models.Index(fields=("session", "objective"), name="sports_practice_rep_obj"),
        ]

    def clean(self):
        if self.outs_before > 2:
            raise ValidationError({"outs_before": "Outs before the rep must be 0, 1 or 2."})

    def __str__(self):
        return f"{self.session_id} · {self.sequence} · {self.objective} · {self.result}"
