from django.contrib.auth import get_user_model
from rest_framework import serializers

from platform_social.serializers import SocialUserSerializer

from .models import (
    SoftballPlateAppearance,
    SportsGame,
    SportsGameInning,
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


class SportsGameInningSerializer(serializers.ModelSerializer):
    team_hits = serializers.SerializerMethodField()

    class Meta:
        model = SportsGameInning
        fields = ("id", "game", "inning", "team_runs", "opponent_runs", "team_hits", "opponent_hits", "created_at", "updated_at")
        read_only_fields = ("id", "team_runs", "team_hits", "created_at", "updated_at")

    def get_team_hits(self, obj):
        return obj.game.plate_appearances.filter(
            inning=obj.inning,
            result__in=(
                SoftballPlateAppearance.Result.SINGLE,
                SoftballPlateAppearance.Result.DOUBLE,
                SoftballPlateAppearance.Result.TRIPLE,
                SoftballPlateAppearance.Result.HOME_RUN,
            ),
        ).count()


class SportsGameSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.group.name", read_only=True)
    lineup_spots = SportsLineupSpotSerializer(many=True, read_only=True)
    plate_appearance_count = serializers.IntegerField(source="plate_appearances.count", read_only=True)
    current_batter = serializers.SerializerMethodField()
    inning_lines = SportsGameInningSerializer(many=True, read_only=True)
    home_runs_for = serializers.SerializerMethodField()
    home_run_allowed = serializers.SerializerMethodField()
    rule_set_detail = serializers.SerializerMethodField()

    class Meta:
        model = SportsGame
        fields = (
            "id", "team", "team_name", "social_event", "game_type", "opponent_name",
            "tournament_name", "round_label", "home_away", "start_at", "end_at", "timezone",
            "venue_name", "address_line1", "city", "state", "notes", "innings_scheduled",
            "rule_set", "rule_set_detail", "home_runs_for", "home_runs_against", "home_run_allowed",
            "status", "current_inning", "outs", "current_batter_order", "current_batter",
            "runs_for", "runs_against", "started_at", "ended_at", "created_by",
            "plate_appearance_count", "lineup_spots", "inning_lines", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "social_event", "status", "current_inning", "outs", "current_batter_order",
            "current_batter", "runs_for", "runs_against", "home_runs_for", "home_run_allowed",
            "rule_set_detail", "started_at", "ended_at", "created_by",
            "plate_appearance_count", "lineup_spots", "created_at", "updated_at",
        )

    def get_home_runs_for(self, obj):
        return obj.plate_appearances.filter(result=SoftballPlateAppearance.Result.HOME_RUN).count()

    def get_home_run_allowed(self, obj):
        rules = getattr(obj, "rule_set", None)
        if not rules or rules.home_run_rule == "UNLIMITED":
            return True
        home_runs_for = self.get_home_runs_for(obj)
        if rules.home_run_rule == "FIXED":
            return rules.home_run_limit is None or home_runs_for < rules.home_run_limit
        if rules.home_run_rule == "ONE_UP":
            return home_runs_for < (int(obj.home_runs_against or 0) + int(rules.home_run_max_ahead or 1))
        return True

    def get_rule_set_detail(self, obj):
        rules = getattr(obj, "rule_set", None)
        if not rules:
            return None
        return {
            "id": rules.id,
            "name": rules.name,
            "competition_type": rules.competition_type,
            "innings": rules.innings,
            "home_run_rule": rules.home_run_rule,
            "home_run_limit": rules.home_run_limit,
            "home_run_max_ahead": rules.home_run_max_ahead,
            "notes": rules.notes,
        }

    def get_current_batter(self, obj):
        spot = next(
            (spot for spot in obj.lineup_spots.all() if spot.batting_order == obj.current_batter_order),
            None,
        )
        return SportsPlayerSerializer(spot.player).data if spot else None
