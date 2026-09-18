from __future__ import annotations

from rest_framework import serializers

from .league_models import (
    LeagueDivision,
    LeagueGame,
    LeagueRosterEntry,
    LeagueSeason,
    LeagueTournament,
    LeagueTournamentEntry,
    LeagueTournamentBye,
    LeagueTeamEntry,
    SportsOrganization,
    SportsOrganizationMembership,
    SportsPlayerIdentity,
    SoftballRuleSet,
)
from .serializers import SportsPlayerSerializer, SportsTeamSerializer


class SportsOrganizationMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = SportsOrganizationMembership
        fields = (
            "id", "organization", "user", "user_email", "user_name", "role", "status",
            "invited_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "invited_by", "created_at", "updated_at")

    def get_user_name(self, obj):
        name = f"{getattr(obj.user, 'first_name', '')} {getattr(obj.user, 'last_name', '')}".strip()
        return name or obj.user.email


class SportsOrganizationSerializer(serializers.ModelSerializer):
    membership_count = serializers.IntegerField(source="memberships.count", read_only=True)
    season_count = serializers.IntegerField(source="seasons.count", read_only=True)

    class Meta:
        model = SportsOrganization
        fields = (
            "id", "name", "slug", "kind", "sport", "city", "state", "description",
            "is_public", "is_active", "created_by", "membership_count", "season_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")


class LeagueSeasonSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    division_count = serializers.IntegerField(source="divisions.count", read_only=True)

    class Meta:
        model = LeagueSeason
        fields = (
            "id", "organization", "organization_name", "name", "starts_on", "ends_on",
            "status", "is_current", "division_count", "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")


class LeagueDivisionSerializer(serializers.ModelSerializer):
    season_name = serializers.CharField(source="season.name", read_only=True)
    organization = serializers.IntegerField(source="season.organization_id", read_only=True)
    organization_name = serializers.CharField(source="season.organization.name", read_only=True)
    team_count = serializers.IntegerField(source="team_entries.count", read_only=True)
    roster_count = serializers.IntegerField(source="roster_entries.count", read_only=True)

    class Meta:
        model = LeagueDivision
        fields = (
            "id", "season", "season_name", "organization", "organization_name", "name", "code",
            "description", "max_roster_size", "is_active", "team_count", "roster_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class LeagueTeamEntrySerializer(serializers.ModelSerializer):
    team_detail = SportsTeamSerializer(source="team", read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)
    season_name = serializers.CharField(source="division.season.name", read_only=True)

    class Meta:
        model = LeagueTeamEntry
        fields = (
            "id", "division", "division_name", "season_name", "team", "team_detail",
            "status", "seed", "joined_at", "updated_at",
        )
        read_only_fields = ("id", "joined_at", "updated_at")


class SoftballRuleSetSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)

    class Meta:
        model = SoftballRuleSet
        fields = (
            "id", "organization", "organization_name", "season", "season_name",
            "division", "division_name", "name", "competition_type", "innings",
            "home_run_rule", "home_run_limit", "home_run_max_ahead", "notes",
            "is_active", "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        instance = self.instance
        organization = attrs.get("organization", getattr(instance, "organization", None))
        season = attrs.get("season", getattr(instance, "season", None))
        division = attrs.get("division", getattr(instance, "division", None))
        home_run_rule = attrs.get("home_run_rule", getattr(instance, "home_run_rule", SoftballRuleSet.HomeRunRule.UNLIMITED))
        home_run_limit = attrs.get("home_run_limit", getattr(instance, "home_run_limit", None))
        if season and organization and season.organization_id != organization.id:
            raise serializers.ValidationError({"season": "Season must belong to this organization."})
        if division and organization and division.season.organization_id != organization.id:
            raise serializers.ValidationError({"division": "Division must belong to this organization."})
        if division and season and division.season_id != season.id:
            raise serializers.ValidationError({"division": "Division must belong to this season."})
        if home_run_rule == SoftballRuleSet.HomeRunRule.FIXED and home_run_limit is None:
            raise serializers.ValidationError({"home_run_limit": "Enter a fixed home-run cap."})
        return attrs


class SportsPlayerIdentitySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    is_claimed = serializers.SerializerMethodField()

    class Meta:
        model = SportsPlayerIdentity
        fields = (
            "id", "email", "display_name", "user", "user_email", "is_claimed",
            "claimed_at", "created_at", "updated_at",
        )
        read_only_fields = ("id", "user", "claimed_at", "created_at", "updated_at")

    def get_is_claimed(self, obj):
        return bool(obj.user_id)


class LeagueRosterEntrySerializer(serializers.ModelSerializer):
    identity_detail = SportsPlayerIdentitySerializer(source="identity", read_only=True)
    player_detail = SportsPlayerSerializer(source="sports_player", read_only=True)
    team_detail = SportsTeamSerializer(source="team", read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)

    class Meta:
        model = LeagueRosterEntry
        fields = (
            "id", "division", "division_name", "team", "team_detail", "identity",
            "identity_detail", "sports_player", "player_detail", "jersey_number", "status",
            "invited_by", "invited_at", "accepted_at", "notes", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "identity", "sports_player", "invited_by", "invited_at", "accepted_at",
            "created_at", "updated_at",
        )



class LeagueGameSerializer(serializers.ModelSerializer):
    home_team_detail = SportsTeamSerializer(source="home_team", read_only=True)
    away_team_detail = SportsTeamSerializer(source="away_team", read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)
    tournament_name = serializers.CharField(source="tournament.name", read_only=True)
    rule_set_name = serializers.CharField(source="rule_set.name", read_only=True)

    class Meta:
        model = LeagueGame
        fields = (
            "id", "division", "division_name", "tournament", "tournament_name", "source",
            "home_team", "home_team_detail", "away_team", "away_team_detail",
            "home_sports_game", "away_sports_game", "rule_set", "rule_set_name",
            "start_at", "end_at", "timezone", "venue_name", "field_name",
            "address_line1", "city", "state", "week_number", "round_number", "bracket_slot",
            "status", "home_score", "away_score", "created_by", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "home_sports_game", "away_sports_game", "created_by", "created_at", "updated_at",
        )


class LeagueTournamentEntrySerializer(serializers.ModelSerializer):
    team_detail = SportsTeamSerializer(source="team", read_only=True)

    class Meta:
        model = LeagueTournamentEntry
        fields = ("id", "tournament", "team", "team_detail", "seed", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class LeagueTournamentByeSerializer(serializers.ModelSerializer):
    team_detail = SportsTeamSerializer(source="team", read_only=True)

    class Meta:
        model = LeagueTournamentBye
        fields = ("id", "tournament", "round_number", "team", "team_detail", "created_at")
        read_only_fields = ("id", "created_at")


class LeagueTournamentSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    division_name = serializers.CharField(source="division.name", read_only=True)
    entry_count = serializers.IntegerField(source="entries.count", read_only=True)

    class Meta:
        model = LeagueTournament
        fields = (
            "id", "organization", "organization_name", "season", "season_name",
            "division", "division_name", "rule_set", "name", "format", "status",
            "starts_on", "ends_on", "venue_name", "address_line1", "city", "state",
            "notes", "entry_count", "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        instance = self.instance
        organization = attrs.get("organization", getattr(instance, "organization", None))
        season = attrs.get("season", getattr(instance, "season", None))
        division = attrs.get("division", getattr(instance, "division", None))
        rule_set = attrs.get("rule_set", getattr(instance, "rule_set", None))
        if season and organization and season.organization_id != organization.id:
            raise serializers.ValidationError({"season": "Season must belong to this organization."})
        if division and organization and division.season.organization_id != organization.id:
            raise serializers.ValidationError({"division": "Division must belong to this organization."})
        if rule_set and organization and rule_set.organization_id != organization.id:
            raise serializers.ValidationError({"rule_set": "Rule set must belong to this organization."})
        return attrs
