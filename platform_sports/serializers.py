from django.contrib.auth import get_user_model
from rest_framework import serializers

from platform_social.serializers import SocialUserSerializer

from .models import (
    SoftballPlateAppearance,
    SportsGame,
    SportsLineupSpot,
    SportsPlayer,
    SportsTeam,
)

User = get_user_model()


class SportsTeamSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True)
    group_kind = serializers.CharField(source="group.kind", read_only=True)
    city = serializers.CharField(source="group.city", read_only=True)
    state = serializers.CharField(source="group.state", read_only=True)
    logo_url = serializers.CharField(source="group.logo_url", read_only=True)

    class Meta:
        model = SportsTeam
        fields = (
            "id", "group", "group_name", "group_kind", "city", "state", "logo_url",
            "sport", "season_name", "league_name", "division_name", "created_by",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")


class SportsPlayerSerializer(serializers.ModelSerializer):
    user_detail = SocialUserSerializer(source="user", read_only=True)

    class Meta:
        model = SportsPlayer
        fields = (
            "id", "team", "user", "user_detail", "display_name", "jersey_number",
            "bats", "throws", "primary_position", "is_active", "sort_order",
            "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")
        extra_kwargs = {"display_name": {"required": False, "allow_blank": True}}

    def validate(self, attrs):
        user = attrs.get("user", getattr(self.instance, "user", None))
        display_name = str(attrs.get("display_name", getattr(self.instance, "display_name", "")) or "").strip()
        if not user and not display_name:
            raise serializers.ValidationError({"display_name": "Enter a player name or link a SyncWorks user."})
        return attrs


class SportsLineupSpotSerializer(serializers.ModelSerializer):
    player_detail = SportsPlayerSerializer(source="player", read_only=True)

    class Meta:
        model = SportsLineupSpot
        fields = (
            "id", "game", "player", "player_detail", "batting_order",
            "defensive_position", "is_starter", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SoftballPlateAppearanceSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.display_name", read_only=True)
    result_label = serializers.CharField(source="get_result_display", read_only=True)

    class Meta:
        model = SoftballPlateAppearance
        fields = (
            "id", "game", "player", "player_name", "sequence", "inning", "result",
            "result_label", "outs_recorded", "rbi", "runs_scored", "notes",
            "created_by", "created_at",
        )
        read_only_fields = ("id", "sequence", "created_by", "created_at")


class SportsGameSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.group.name", read_only=True)
    lineup_spots = SportsLineupSpotSerializer(many=True, read_only=True)
    plate_appearance_count = serializers.IntegerField(source="plate_appearances.count", read_only=True)
    current_batter = serializers.SerializerMethodField()

    class Meta:
        model = SportsGame
        fields = (
            "id", "team", "team_name", "social_event", "game_type", "opponent_name",
            "tournament_name", "round_label", "home_away", "start_at", "end_at", "timezone",
            "venue_name", "address_line1", "city", "state", "notes", "innings_scheduled",
            "status", "current_inning", "outs", "current_batter_order", "current_batter",
            "runs_for", "runs_against", "started_at", "ended_at", "created_by",
            "plate_appearance_count", "lineup_spots", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "social_event", "status", "current_inning", "outs", "current_batter_order",
            "current_batter", "runs_for", "runs_against", "started_at", "ended_at", "created_by",
            "plate_appearance_count", "lineup_spots", "created_at", "updated_at",
        )

    def get_current_batter(self, obj):
        spot = next(
            (spot for spot in obj.lineup_spots.all() if spot.batting_order == obj.current_batter_order),
            None,
        )
        return SportsPlayerSerializer(spot.player).data if spot else None
