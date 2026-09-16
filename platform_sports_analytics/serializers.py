from rest_framework import serializers

from .models import GameCastShare, SoftballPlayContext


class SoftballPlayContextSerializer(serializers.ModelSerializer):
    had_runner_move_opportunity = serializers.BooleanField(read_only=True)

    class Meta:
        model = SoftballPlayContext
        fields = (
            "id",
            "plate_appearance",
            "batted_ball_type",
            "spray_zone",
            "spray_x",
            "spray_y",
            "runner_on_first_before",
            "runner_on_second_before",
            "runner_on_third_before",
            "runners_advanced",
            "productive_out",
            "quality_note",
            "had_runner_move_opportunity",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at", "had_runner_move_opportunity")


class GameCastShareSerializer(serializers.ModelSerializer):
    class Meta:
        model = GameCastShare
        fields = (
            "id",
            "game",
            "token",
            "enabled",
            "show_player_stats",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "token", "created_by", "created_at", "updated_at")
