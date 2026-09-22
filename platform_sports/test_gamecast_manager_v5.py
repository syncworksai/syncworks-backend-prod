from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam


User = get_user_model()


class GameBookManagerV5Tests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="manager-v5@example.com", email="manager-v5@example.com", password="pass-12345")
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
        self.player = SportsPlayer.objects.create(team=self.team, display_name="Player One", created_by=self.owner)
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Opponent",
            start_at=timezone.now() - timedelta(hours=1),
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(game=self.game, player=self.player, batting_order=1)
        self.client.force_authenticate(self.owner)

    def test_delete_book_removes_stat_source_and_resets_game_shell(self):
        self.game.status = SportsGame.Status.LIVE
        self.game.runs_for = 2
        self.game.runner_on_first = True
        self.game.save()
        SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.player,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.SINGLE,
            runs_scored=2,
            created_by=self.owner,
        )
        response = self.client.post(f"/api/v1/sports/games/{self.game.id}/delete-book/")
        self.assertEqual(response.status_code, 200)
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, SportsGame.Status.SCHEDULED)
        self.assertEqual(self.game.runs_for, 0)
        self.assertFalse(self.game.runner_on_first)
        self.assertEqual(self.game.plate_appearances.count(), 0)
        self.assertTrue(response.data["stats_removed"])

    def test_live_play_persists_base_state_for_gamecast(self):
        start = self.client.post(f"/api/v1/sports/games/{self.game.id}/start/")
        self.assertEqual(start.status_code, 200)
        response = self.client.post(
            f"/api/v1/sports/games/{self.game.id}/play/",
            {
                "result": "1B",
                "outs_recorded": 0,
                "rbi": 0,
                "runs_scored": 0,
                "runner_on_first_after": True,
                "runner_on_second_after": False,
                "runner_on_third_after": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.game.refresh_from_db()
        self.assertTrue(self.game.runner_on_first)
        self.assertFalse(self.game.runner_on_second)
