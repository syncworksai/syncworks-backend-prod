from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance,
    SportsGame,
    SportsLineupSpot,
    SportsPlayer,
    SportsTeam,
)


User = get_user_model()


class GameCastTokenAndHistoricalEditTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="gamecast-edit-coach",
            email="gamecast-edit@example.test",
            password="x",
        )
        self.group = SocialGroup.objects.create(
            name="GameCast Edit Team",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.coach,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            created_by=self.coach,
        )
        self.first = SportsGame.objects.create(
            team=self.team,
            opponent_name="First",
            start_at=timezone.now(),
            status=SportsGame.Status.FINAL,
            runs_for=10,
            runs_against=9,
            created_by=self.coach,
        )
        self.second = SportsGame.objects.create(
            team=self.team,
            opponent_name="Second",
            start_at=timezone.now(),
            status=SportsGame.Status.FINAL,
            runs_for=20,
            runs_against=12,
            created_by=self.coach,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team,
            display_name="Book Hitter",
            jersey_number="7",
            primary_position="2B",
            created_by=self.coach,
        )
        SportsLineupSpot.objects.create(
            game=self.first,
            player=self.player,
            batting_order=1,
            defensive_position="2B",
        )
        SoftballPlateAppearance.objects.create(
            game=self.first,
            player=self.player,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.HOME_RUN,
            rbi=1,
            runs_scored=1,
            created_by=self.coach,
        )
        self.client.force_authenticate(self.coach)

    def test_every_game_has_unique_gamecast_token(self):
        self.assertTrue(SportsGame._meta.get_field("gamecast_token").unique)
        self.assertNotEqual(self.first.gamecast_token, self.second.gamecast_token)

    def test_enabled_gamecast_token_resolves_only_its_game(self):
        enabled = self.client.post(
            f"/api/v1/sports/games/{self.first.id}/gamecast/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(enabled.status_code, 200, enabled.data)
        public = self.client.get(
            "/api/v1/sports/games/gamecast-public/",
            {"token": enabled.data["token"]},
        )
        self.assertEqual(public.status_code, 200, public.data)
        self.assertEqual(public.data["game"]["id"], self.first.id)
        self.assertIsNone(public.data["game"]["current_batter"])
        self.assertEqual(public.data["lineup"][0]["player_detail"]["display_name"], "Book Hitter")
        self.assertNotIn("user", public.data["lineup"][0]["player_detail"])
        self.assertEqual(public.data["book"][0]["result"], SoftballPlateAppearance.Result.HOME_RUN)
        self.assertEqual(public.data["book_players"][0]["stats"]["h"], 1)
        self.assertEqual(public.data["book_players"][0]["stats"]["hr"], 1)
        self.assertEqual(public.data["game_totals"]["h"], 1)

    def test_manager_edits_final_score_without_reopening_game(self):
        response = self.client.post(
            f"/api/v1/sports/games/{self.first.id}/edit-final/",
            {"runs_for": 11, "runs_against": 9},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], SportsGame.Status.FINAL)
        self.assertEqual(response.data["runs_for"], 11)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, SportsGame.Status.FINAL)
        self.assertEqual((self.first.runs_for, self.first.runs_against), (11, 9))
