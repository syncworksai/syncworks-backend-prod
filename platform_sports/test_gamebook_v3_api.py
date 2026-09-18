from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance,
    SportsGame,
    SportsLineupSpot,
    SportsPlayer,
    SportsTeam,
)
from platform_sports_analytics.models import SoftballPlayContext

User = get_user_model()


class GameBookV3ApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="gamebook-v3-owner", email="gamebook-v3@example.com", password="x")
        self.group = SocialGroup.objects.create(name="GameBook V3 Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            created_by=self.owner,
        )
        self.starter = SportsPlayer.objects.create(team=self.team, display_name="Starter", jersey_number="7", created_by=self.owner)
        self.sub = SportsPlayer.objects.create(team=self.team, display_name="Bench Player", jersey_number="27", created_by=self.owner)
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Opponent",
            start_at=timezone.now() - timedelta(minutes=30),
            status=SportsGame.Status.LIVE,
            current_inning=2,
            current_batter_order=1,
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(game=self.game, player=self.starter, batting_order=1, defensive_position="SS")
        pa = SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.starter,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.SINGLE,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=pa,
            spray_zone=SoftballPlayContext.SprayZone.RIGHT_CENTER,
            batted_ball_type=SoftballPlayContext.BattedBallType.LINE,
            created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)

    def test_player_card_exposes_season_and_field_tendency(self):
        response = self.client.get(reverse("sports-player-card", args=[self.starter.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["seasons"][0]["season"], "Fall 2026")
        self.assertEqual(response.data["seasons"][0]["scope"], "LEAGUE")
        right_center = next(row for row in response.data["tendencies"]["spray_field"] if row["zone"] == "RIGHT_CENTER")
        self.assertEqual(right_center["pct"], 1.0)
        self.assertEqual(response.data["tendencies"]["sample_size"], 1)

    def test_live_substitution_returns_outgoing_player_to_bench(self):
        response = self.client.post(
            reverse("sports-games-substitute", args=[self.game.id]),
            {"batting_order": 1, "incoming_player": self.sub.id, "defensive_position": "SS"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["lineup_spots"][0]["player"], self.sub.id)
        bench_ids = {row["id"] for row in response.data["bench_players"]}
        self.assertIn(self.starter.id, bench_ids)
        self.assertEqual(response.data["substitutions"][0]["outgoing_player"], self.starter.id)
        self.assertEqual(response.data["substitutions"][0]["incoming_player"], self.sub.id)
