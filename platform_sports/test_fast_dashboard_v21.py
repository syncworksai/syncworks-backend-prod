from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam,
)


User = get_user_model()


class FastSportsDashboardTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="fast-coach", email="fast-coach@example.com", password="test",
        )
        self.group = SocialGroup.objects.create(
            name="Speed-test Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.coach,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026", created_by=self.coach,
        )
        self.players = [
            SportsPlayer.objects.create(
                team=self.team, display_name=f"Player {index}",
                jersey_number=str(index), created_by=self.coach,
            ) for index in range(1, 13)
        ]
        start = timezone.now() + timedelta(days=3)
        self.final = SportsGame.objects.create(
            team=self.team, opponent_name="Previous opponent",
            start_at=start - timedelta(days=9), status=SportsGame.Status.FINAL,
            runs_for=14, runs_against=6, created_by=self.coach,
        )
        self.upcoming = [
            SportsGame.objects.create(
                team=self.team, opponent_name=f"Upcoming {index}",
                start_at=start + timedelta(hours=index), status=SportsGame.Status.SCHEDULED,
                home_away="HOME" if index else "AWAY",
                venue_name=f"Field {index + 1}", created_by=self.coach,
            ) for index in range(2)
        ]
        for game in (self.final, *self.upcoming):
            for order, player in enumerate(self.players, start=1):
                SportsLineupSpot.objects.create(
                    game=game, player=player, batting_order=order,
                    defensive_position="SS" if order == 1 else "EH",
                )
        SoftballPlateAppearance.objects.create(
            game=self.final, player=self.players[0], sequence=1, inning=1,
            result="2B", rbi=2, runs_scored=2, created_by=self.coach,
        )

    def test_compact_dashboard_preserves_roster_record_and_both_games(self):
        self.client.force_authenticate(self.coach)
        with CaptureQueriesContext(connection) as sql:
            result = self.client.get(
                f"/api/v1/sports/teams/{self.team.id}/dashboard/?compact=1"
            )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["record"]["wins"], 1)
        self.assertEqual(result.data["team_stats"]["runs_for"], 14)
        self.assertEqual(result.data["team_stats"]["hits"], 1)
        self.assertEqual(len(result.data["players"]), 12)
        self.assertEqual(len(result.data["upcoming_games"]), 2)
        self.assertEqual(
            [game["venue_name"] for game in result.data["upcoming_games"]],
            ["Field 1", "Field 2"],
        )
        self.assertEqual(
            len(result.data["upcoming_games"][0]["lineup_spots"]), 12
        )
        self.assertEqual(result.data["upcoming_games"][0]["bench_players"], [])
        self.assertLess(len(sql), 75, "The dashboard must not run a query per player or game.")

    def test_private_dashboard_requires_membership(self):
        outsider = User.objects.create_user(
            username="fast-outsider", email="fast-outsider@example.com", password="test",
        )
        self.client.force_authenticate(outsider)
        response = self.client.get(
            f"/api/v1/sports/teams/{self.team.id}/dashboard/?compact=1"
        )
        self.assertEqual(response.status_code, 404)
