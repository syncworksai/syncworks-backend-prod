from datetime import timedelta

from django.contrib.auth import get_user_model
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
from platform_sports.ops_models import SoftballStatLedgerEntry
from platform_sports_analytics.models import SoftballPlayContext


User = get_user_model()


class GameBookLiveIqTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="gamebook-owner",
            email="gamebook-owner@example.com",
            password="pass12345",
        )
        self.group = SocialGroup.objects.create(
            name="Live IQ Softball",
            kind=SocialGroup.Kind.TEAM,
            created_by=self.owner,
        )
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
            league_name="City League",
            created_by=self.owner,
        )
        self.p1 = SportsPlayer.objects.create(
            team=self.team,
            display_name="Player One",
            jersey_number="7",
            primary_position="SS",
            created_by=self.owner,
        )
        self.p2 = SportsPlayer.objects.create(
            team=self.team,
            display_name="Player Two",
            jersey_number="12",
            primary_position="2B",
            created_by=self.owner,
        )
        self.sub = SportsPlayer.objects.create(
            team=self.team,
            display_name="Bench Bat",
            jersey_number="21",
            primary_position="OF",
            created_by=self.owner,
        )
        self.live_game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Visitors",
            start_at=timezone.now(),
            status=SportsGame.Status.LIVE,
            current_batter_order=1,
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(
            game=self.live_game,
            player=self.p1,
            batting_order=1,
            defensive_position="SS",
        )
        SportsLineupSpot.objects.create(
            game=self.live_game,
            player=self.p2,
            batting_order=2,
            defensive_position="2B",
        )
        self.client.force_authenticate(user=self.owner)

    def test_manager_can_substitute_bench_player_into_same_batting_slot(self):
        response = self.client.post(
            f"/api/v1/sports/games/{self.live_game.id}/substitute/",
            {
                "out_player": self.p1.id,
                "in_player": self.sub.id,
                "defensive_position": "MM",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spot = SportsLineupSpot.objects.get(game=self.live_game, batting_order=1)
        self.assertEqual(spot.player_id, self.sub.id)
        self.assertEqual(spot.defensive_position, "MM")
        self.assertFalse(spot.is_starter)

        self.live_game.refresh_from_db()
        self.assertEqual(self.live_game.current_batter_order, 1)
        self.assertEqual(response.data["game"]["current_batter"]["id"], self.sub.id)
        self.assertEqual(response.data["substitution"]["out_player"]["id"], self.p1.id)

    def test_player_card_returns_previous_at_bat_tendencies_and_season_history(self):
        prior_game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Earlier Team",
            game_type=SportsGame.GameType.LEAGUE,
            start_at=timezone.now() - timedelta(days=7),
            status=SportsGame.Status.FINAL,
            created_by=self.owner,
        )
        pa1 = SoftballPlateAppearance.objects.create(
            game=prior_game,
            player=self.p1,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.SINGLE,
            rbi=1,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=pa1,
            spray_zone="LEFT",
            batted_ball_type="LINE",
            created_by=self.owner,
        )
        pa2 = SoftballPlateAppearance.objects.create(
            game=prior_game,
            player=self.p1,
            sequence=2,
            inning=3,
            result=SoftballPlateAppearance.Result.OUT,
            outs_recorded=1,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=pa2,
            spray_zone="RIGHT_CENTER",
            batted_ball_type="FLY",
            created_by=self.owner,
        )
        SoftballPlateAppearance.objects.create(
            game=self.live_game,
            player=self.p1,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.HOME_RUN,
            rbi=1,
            runs_scored=1,
            created_by=self.owner,
        )
        SoftballStatLedgerEntry.objects.create(
            team=self.team,
            player=self.p1,
            season_name="Fall 2025",
            scope=SoftballStatLedgerEntry.Scope.TOURNAMENT,
            games=4,
            pa=12,
            ab=10,
            hits=5,
            doubles=1,
            home_runs=1,
            rbi=4,
            runs=3,
            created_by=self.owner,
        )

        response = self.client.get(
            f"/api/v1/sports/advanced/players/{self.p1.id}/card/?exclude_game={self.live_game.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tendencies = response.data["tendencies"]
        self.assertEqual(tendencies["sample_pa"], 2)
        self.assertEqual(tendencies["spray_sample"], 2)
        self.assertEqual(tendencies["field_zones"]["left"]["pct"], 50.0)
        self.assertEqual(tendencies["field_zones"]["right_center"]["pct"], 50.0)
        self.assertEqual(tendencies["hit_pct"], 50.0)
        self.assertTrue(
            any(
                row["season"] == "Fall 2025" and row["scope"] == "TOURNAMENT"
                for row in response.data["seasons"]
            )
        )
