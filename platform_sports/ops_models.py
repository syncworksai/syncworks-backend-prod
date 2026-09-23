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
    birth_date = models.DateField(null=True, blank=True)
    show_age = models.BooleanField(default=False)
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


class SportsWeeklyPoll(models.Model):
    """One coach-published RSVP per local Monday; individual game responses remain canonical."""
    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="weekly_polls")
    week_start = models.DateField()
    deadline = models.DateTimeField(null=True, blank=True)
    message = models.CharField(max_length=300, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_weekly_polls_created")
    published_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("week_start", "id")
        constraints = [
            models.UniqueConstraint(fields=("team", "week_start"), name="sports_unique_weekly_poll"),
        ]


class SportsTeamPoll(models.Model):
    """General-purpose group-chat poll, separate from the weekly game RSVP."""
    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="chat_polls")
    question = models.CharField(max_length=220)
    options = models.JSONField(default=list)
    closes_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_chat_polls_created")
    created_at = models.DateTimeField(auto_now_add=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at", "-id")


class SportsTeamPollVote(models.Model):
    poll = models.ForeignKey(SportsTeamPoll, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sports_team_poll_votes")
    option_index = models.PositiveSmallIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("poll", "user"), name="sports_unique_team_poll_vote"),
        ]


class SportsCoachAward(models.Model):
    class Kind(models.TextChoices):
        GOLD_GLOVE = "GOLD_GLOVE", "Golden Glove"
        HUSTLE = "HUSTLE", "Hustle Award"
        TEAM_FIRST = "TEAM_FIRST", "Team-First Award"
        PLAYER_WEEK = "PLAYER_WEEK", "Player of the Week"
        ROOKIE_YEAR = "ROOKIE_YEAR", "Rookie of the Year"
        MOST_IMPROVED = "MOST_IMPROVED", "Most Improved"
        CUSTOM = "CUSTOM", "Custom Coach Award"

    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="coach_awards")
    player = models.ForeignKey("platform_sports.SportsPlayer", on_delete=models.PROTECT, related_name="coach_awards")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    title = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=500)
    season_name = models.CharField(max_length=120)
    award_date = models.DateField(default=timezone.localdate)
    game = models.ForeignKey("platform_sports.SportsGame", null=True, blank=True, on_delete=models.SET_NULL, related_name="coach_awards")
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sports_awards_issued")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sports_awards_revoked")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-award_date", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("team", "season_name"),
                condition=models.Q(kind="ROOKIE_YEAR", revoked_at__isnull=True),
                name="sports_unique_active_rookie_award",
            ),
            models.UniqueConstraint(
                fields=("team", "kind", "award_date"),
                condition=models.Q(kind="PLAYER_WEEK", revoked_at__isnull=True),
                name="sports_unique_weekly_player_award",
            ),
        ]
