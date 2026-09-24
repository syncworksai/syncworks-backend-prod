from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam
from platform_sports.ops_models import SportsPracticeSession, SportsPracticeRep


User = get_user_model()


class PracticeModeAndSituationsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="practice-player", email="practice@example.com", password="x")
        self.coach = User.objects.create_user(username="practice-coach", email="coach@example.com", password="x")
        self.group = SocialGroup.objects.create(
            name="Practice Team",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.coach, role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.user, role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL, season_name="Fall 2026", created_by=self.coach
        )
        self.player = SportsPlayer.objects.create(
            team=self.team, user=self.user, display_name="Practice Player",
            jersey_number="7", created_by=self.coach,
        )

    def test_player_logs_situations_and_gets_private_comparison(self):
        self.client.force_authenticate(self.user)
        session = self.client.post("/api/v1/sports/practice-sessions/", {
            "team": self.team.id, "player": self.player.id, "kind": "SITUATIONS",
            "title": "Situations BP",
        }, format="json")
        self.assertEqual(session.status_code, 201, session.data)
        session_id = session.data["id"]

        for successful, result in ((True, "SF"), (False, "OUT"), (True, "1B")):
            rep = self.client.post(f"/api/v1/sports/practice-sessions/{session_id}/add-rep/", {
                "outs_before": 1,
                "base_state": "3",
                "objective": "SAC_FLY",
                "result": result,
                "runners_advanced": 1 if successful else 0,
                "rbi": 1 if successful else 0,
                "successful": successful,
            }, format="json")
            self.assertEqual(rep.status_code, 201, rep.data)

        summary = self.client.get(
            f"/api/v1/sports/practice-sessions/summary/?team={self.team.id}&player={self.player.id}"
        )
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["practice"]["reps"], 3)
        sac = next(row for row in summary.data["objectives"] if row["key"] == "SAC_FLY")
        self.assertEqual(sac["practice_attempts"], 3)
        self.assertEqual(sac["practice_successes"], 2)

    def test_live_game_records_situation_context_for_later_comparison(self):
        game = SportsGame.objects.create(
            team=self.team, opponent_name="Opponent", start_at=timezone.now(),
            status=SportsGame.Status.SCHEDULED, created_by=self.coach,
        )
        SportsLineupSpot.objects.create(
            game=game, player=self.player, batting_order=1, defensive_position="SS", is_starter=True,
        )
        self.client.force_authenticate(self.coach)
        started = self.client.post(f"/api/v1/sports/games/{game.id}/start/", {}, format="json")
        self.assertEqual(started.status_code, 200, started.data)

        play = self.client.post(f"/api/v1/sports/games/{game.id}/play/", {
            "result": "SF",
            "outs_recorded": 1,
            "rbi": 1,
            "runs_scored": 1,
            "base_state": "3",
            "situation_objective": "SAC_FLY",
            "runners_advanced": 1,
            "situation_success": True,
        }, format="json")
        self.assertEqual(play.status_code, 201, play.data)
        row = play.data["play"]
        self.assertEqual(row["outs_before"], 0)
        self.assertEqual(row["base_state"], "3")
        self.assertEqual(row["situation_objective"], "SAC_FLY")
        self.assertTrue(row["situation_success"])

    def test_teammate_cannot_read_another_players_practice(self):
        stranger = User.objects.create_user(username="practice-stranger", email="stranger@example.com", password="x")
        GroupMembership.objects.create(
            group=self.group, user=stranger, role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        SportsPracticeSession.objects.create(
            team=self.team, player=self.player, kind="BP", title="Private BP", created_by=self.user
        )
        self.client.force_authenticate(stranger)
        response = self.client.get(
            f"/api/v1/sports/practice-sessions/summary/?team={self.team.id}&player={self.player.id}"
        )
        self.assertEqual(response.status_code, 403)


    def test_player_center_returns_every_game_on_next_game_day(self):
        from datetime import timedelta
        from platform_sports.views import sync_game_social_event

        start = timezone.now() + timedelta(days=3)
        start = start.replace(hour=23, minute=30, second=0, microsecond=0)
        games = []
        for offset_hours, opponent in ((0, "Doubleheader One"), (1, "Doubleheader Two"), (25, "Next Day")):
            game = SportsGame.objects.create(
                team=self.team,
                opponent_name=opponent,
                start_at=start + timedelta(hours=offset_hours),
                status=SportsGame.Status.SCHEDULED,
                venue_name="Dean Fain Park · Field 1",
                home_away="HOME" if offset_hours else "AWAY",
                created_by=self.coach,
            )
            sync_game_social_event(game)
            games.append(game)

        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/v1/sports/teams/{self.team.id}/player-center/")
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["next_game_day"]
        # The first two games are the same local game day; the third is not.
        self.assertEqual([row["game"]["id"] for row in rows], [games[0].id, games[1].id])
        self.assertTrue(all(row["my_response"]["response"] == "PENDING" for row in rows))
