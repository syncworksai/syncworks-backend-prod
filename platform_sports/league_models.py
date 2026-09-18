from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


SPORT_CHOICES = (
    ("SOFTBALL", "Softball"),
    ("BASEBALL", "Baseball"),
    ("BASKETBALL", "Basketball"),
    ("SOCCER", "Soccer"),
    ("FOOTBALL", "Football"),
    ("VOLLEYBALL", "Volleyball"),
    ("OTHER", "Other"),
)


class SportsOrganization(models.Model):
    class Kind(models.TextChoices):
        LEAGUE = "LEAGUE", "League"
        SANCTION = "SANCTION", "Sanction / association"
        CLUB_NETWORK = "CLUB_NETWORK", "Club network"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=190, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.LEAGUE)
    sport = models.CharField(max_length=20, choices=SPORT_CHOICES, default="SOFTBALL")
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_organizations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        indexes = [models.Index(fields=("sport", "is_active"), name="sports_org_sport_active")]

    def __str__(self):
        return self.name


class SportsOrganizationMembership(models.Model):
    class Role(models.TextChoices):
        COMMISSIONER = "COMMISSIONER", "Commissioner"
        ADMIN = "ADMIN", "Admin"
        STAFF = "STAFF", "Staff"

    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        REMOVED = "REMOVED", "Removed"

    organization = models.ForeignKey(
        SportsOrganization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_organization_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_organization_invites_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="sports_unique_org_membership",
            )
        ]
        indexes = [models.Index(fields=("user", "status"), name="sports_org_member_user")]

    def __str__(self):
        return f"{self.organization.name} · {self.user_id} · {self.role}"


class LeagueSeason(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        COMPLETE = "COMPLETE", "Complete"
        ARCHIVED = "ARCHIVED", "Archived"

    organization = models.ForeignKey(
        SportsOrganization,
        on_delete=models.CASCADE,
        related_name="seasons",
    )
    name = models.CharField(max_length=140)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    is_current = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_seasons_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_current", "-starts_on", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                name="sports_unique_org_season_name",
            )
        ]

    def clean(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": "Season end date cannot be before its start date."})

    def __str__(self):
        return f"{self.organization.name} · {self.name}"


class LeagueDivision(models.Model):
    season = models.ForeignKey(LeagueSeason, on_delete=models.CASCADE, related_name="divisions")
    name = models.CharField(max_length=140)
    code = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    max_roster_size = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("season", "name"),
                name="sports_unique_season_division_name",
            )
        ]

    def __str__(self):
        return f"{self.season} · {self.name}"


class LeagueTeamEntry(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        REMOVED = "REMOVED", "Removed"

    division = models.ForeignKey(LeagueDivision, on_delete=models.CASCADE, related_name="team_entries")
    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="league_entries")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    seed = models.PositiveSmallIntegerField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("seed", "team__group__name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("division", "team"),
                name="sports_unique_division_team",
            )
        ]
        indexes = [models.Index(fields=("division", "status"), name="sports_div_team_status")]

    def clean(self):
        if self.team_id and self.division_id:
            org_sport = self.division.season.organization.sport
            if self.team.sport != org_sport:
                raise ValidationError({"team": "Team sport must match the league organization sport."})

    def __str__(self):
        return f"{self.division} · {self.team}"


class SoftballRuleSet(models.Model):
    class CompetitionType(models.TextChoices):
        LEAGUE = "LEAGUE", "League"
        TOURNAMENT = "TOURNAMENT", "Tournament"
        OTHER = "OTHER", "Other"

    class HomeRunRule(models.TextChoices):
        UNLIMITED = "UNLIMITED", "Unlimited"
        FIXED = "FIXED", "Fixed cap"
        ONE_UP = "ONE_UP", "One-up / San Diego"

    organization = models.ForeignKey(
        SportsOrganization,
        on_delete=models.CASCADE,
        related_name="softball_rule_sets",
    )
    season = models.ForeignKey(
        LeagueSeason,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="softball_rule_sets",
    )
    division = models.ForeignKey(
        LeagueDivision,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="softball_rule_sets",
    )
    name = models.CharField(max_length=140)
    competition_type = models.CharField(
        max_length=12,
        choices=CompetitionType.choices,
        default=CompetitionType.LEAGUE,
    )
    innings = models.PositiveSmallIntegerField(default=7)
    home_run_rule = models.CharField(
        max_length=12,
        choices=HomeRunRule.choices,
        default=HomeRunRule.UNLIMITED,
    )
    home_run_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    home_run_max_ahead = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="softball_rule_sets_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization__name", "competition_type", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                name="sports_unique_org_ruleset_name",
            )
        ]
        indexes = [
            models.Index(fields=("organization", "competition_type", "is_active"), name="sports_ruleset_lookup"),
        ]

    def clean(self):
        if self.season_id and self.season.organization_id != self.organization_id:
            raise ValidationError({"season": "Rule-set season must belong to the selected organization."})
        if self.division_id:
            if self.division.season.organization_id != self.organization_id:
                raise ValidationError({"division": "Rule-set division must belong to the selected organization."})
            if self.season_id and self.division.season_id != self.season_id:
                raise ValidationError({"division": "Rule-set division must belong to the selected season."})
        if self.home_run_rule == self.HomeRunRule.FIXED and self.home_run_limit is None:
            raise ValidationError({"home_run_limit": "Enter a home-run cap for a fixed rule."})

    def __str__(self):
        return f"{self.organization.name} · {self.name}"


class SportsPlayerIdentity(models.Model):
    email = models.EmailField(unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sports_identity",
    )
    display_name = models.CharField(max_length=180, blank=True)
    claim_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name", "email", "id")

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def claim(self, user):
        user_email = (getattr(user, "email", "") or "").strip().lower()
        if not user_email or user_email != self.email:
            raise ValidationError("The signed-in account email must match this roster invitation.")
        if self.user_id and self.user_id != user.id:
            raise ValidationError("This sports identity is already claimed by another account.")
        self.user = user
        self.claimed_at = self.claimed_at or timezone.now()
        self.save(update_fields=("user", "claimed_at", "updated_at"))

    def __str__(self):
        return self.display_name or self.email


class LeagueRosterEntry(models.Model):
    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        INELIGIBLE = "INELIGIBLE", "Ineligible"
        REMOVED = "REMOVED", "Removed"

    division = models.ForeignKey(LeagueDivision, on_delete=models.CASCADE, related_name="roster_entries")
    team = models.ForeignKey("platform_sports.SportsTeam", on_delete=models.CASCADE, related_name="league_roster_entries")
    identity = models.ForeignKey(SportsPlayerIdentity, on_delete=models.PROTECT, related_name="roster_entries")
    sports_player = models.ForeignKey(
        "platform_sports.SportsPlayer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="league_roster_entries",
    )
    jersey_number = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INVITED)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="league_roster_invites_sent",
    )
    invited_at = models.DateTimeField(default=timezone.now)
    accepted_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("team__group__name", "identity__display_name", "identity__email", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("division", "team", "identity"),
                name="sports_unique_div_team_identity",
            )
        ]
        indexes = [
            models.Index(fields=("division", "team", "status"), name="sports_roster_lookup"),
        ]

    def clean(self):
        if self.division_id and self.team_id and not LeagueTeamEntry.objects.filter(
            division_id=self.division_id,
            team_id=self.team_id,
            status=LeagueTeamEntry.Status.ACTIVE,
        ).exists():
            raise ValidationError({"team": "Team must be active in this division before players can be rostered."})
        if self.sports_player_id and self.sports_player.team_id != self.team_id:
            raise ValidationError({"sports_player": "Sports player must belong to the rostered team."})

    def __str__(self):
        return f"{self.team} · {self.identity}"
