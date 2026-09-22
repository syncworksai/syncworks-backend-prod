from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SoftballPlayContext(models.Model):
    class BattedBallType(models.TextChoices):
        GROUND = "GROUND", "Ground ball"
        LINE = "LINE", "Line drive"
        FLY = "FLY", "Fly ball"
        POP = "POP", "Pop up"

    class SprayZone(models.TextChoices):
        LEFT_LINE = "LEFT_LINE", "Left-field line"
        LEFT = "LEFT", "Left field"
        LEFT_CENTER = "LEFT_CENTER", "Left center"
        CENTER = "CENTER", "Center field"
        RIGHT_CENTER = "RIGHT_CENTER", "Right center"
        RIGHT = "RIGHT", "Right field"
        RIGHT_LINE = "RIGHT_LINE", "Right-field line"
        INFIELD_LEFT = "INFIELD_LEFT", "Left infield"
        INFIELD_MIDDLE = "INFIELD_MIDDLE", "Middle infield"
        INFIELD_RIGHT = "INFIELD_RIGHT", "Right infield"

    plate_appearance = models.OneToOneField(
        "platform_sports.SoftballPlateAppearance",
        on_delete=models.CASCADE,
        related_name="advanced_context",
    )
    batted_ball_type = models.CharField(max_length=12, choices=BattedBallType.choices, blank=True)
    spray_zone = models.CharField(max_length=20, choices=SprayZone.choices, blank=True)
    spray_x = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Normalized field X coordinate from 0 to 100.",
    )
    spray_y = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Normalized field Y coordinate from 0 to 100.",
    )
    runner_on_first_before = models.BooleanField(default=False)
    runner_on_second_before = models.BooleanField(default=False)
    runner_on_third_before = models.BooleanField(default=False)
    runners_advanced = models.PositiveSmallIntegerField(default=0)
    productive_out = models.BooleanField(default=False)
    quality_note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="softball_play_context_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plate_appearance__game_id", "plate_appearance__sequence")
        indexes = [
            models.Index(fields=("spray_zone", "batted_ball_type"), name="sports_ctx_spray_type"),
        ]

    @property
    def had_runner_move_opportunity(self):
        return self.runner_on_first_before or self.runner_on_second_before or self.runner_on_third_before


class GameCastShare(models.Model):
    game = models.OneToOneField(
        "platform_sports.SportsGame",
        on_delete=models.CASCADE,
        related_name="gamecast_share",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enabled = models.BooleanField(default=False)
    show_live_score = models.BooleanField(default=True)
    show_current_batter = models.BooleanField(default=True)
    show_lineup = models.BooleanField(default=True)
    show_recent_plays = models.BooleanField(default=True)
    show_player_stats = models.BooleanField(default=True)
    allow_follow = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sports_gamecast_shares_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
