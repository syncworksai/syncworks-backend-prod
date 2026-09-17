from __future__ import annotations

from rest_framework import serializers

from .league_models import (
    LeagueDivision,
    LeagueRosterEntry,
    LeagueSeason,
    LeagueTeamEntry,
    SportsOrganization,
    SportsOrganizationMembership,
    SportsPlayerIdentity,
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
