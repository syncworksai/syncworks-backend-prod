from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam


User = get_user_model()


class GameCastManagerV5Tests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="manager-v5@example.com", email="manager-v5@example.com", password="test-pass-123")
        self.viewer = User.objects.create_user(username="viewer-v5@example.com", email="viewer-v5@example.com", password="test-pass-123")
        self.group = SocialGroup.objects.create(
            name="V5 Softball",
            kind=SocialGroup.Kind.TEAM,
            category=SocialGroup.Category.SPORTS,
            visibility=SocialGroup.Visibility.PUBLIC,
            created_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.owner)
        self.player = SportsPlayer.objects.create(team=self.team, display_name="Test Batter", jersey_number="7", created_by=self.owner)
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Test Opponent",
            start_at=timezone.now() + timedelta(hours=1),
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(game=self.game, player=self.player, batting_order=1, defensive_position="2B")

    def test_manager_can_enable_and_view_gamecast(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/sports/games/{self.game.id}/gamecast/",
            {"enabled": True, "show_batter": True, "show_recent_plays": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["enabled"])
        token = response.data["token"]

        self.client.force_authenticate(self.viewer)
        public = self.client.get("/api/v1/sports/games/gamecast-public/", {"token": token})
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data["game"]["team_name"], "V5 Softball")
        self.assertEqual(public.data["game"]["current_batter"]["display_name"], "Test Batter")

    def test_delete_book_removes_stat_events_but_keeps_game(self):
        SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.player,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.SINGLE,
            runs_scored=1,
            rbi=1,
            created_by=self.owner,
        )
        self.game.status = SportsGame.Status.FINAL
        self.game.runs_for = 1
        self.game.runs_against = 0
        self.game.save()

        self.client.force_authenticate(self.owner)
        response = self.client.post(f"/api/v1/sports/games/{self.game.id}/delete-book/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, SportsGame.Status.SCHEDULED)
        self.assertEqual(self.game.runs_for, 0)
        self.assertEqual(self.game.runs_against, 0)
        self.assertFalse(SoftballPlateAppearance.objects.filter(game=self.game).exists())
        self.assertTrue(SportsGame.objects.filter(pk=self.game.pk).exists())
