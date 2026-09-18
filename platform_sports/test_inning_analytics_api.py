from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam

User = get_user_model()


class SportsInningAnalyticsApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="sports-analytics-owner", email="sports-analytics-owner@example.com", password="x")
        self.group = SocialGroup.objects.create(name="Analytics Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(group=self.group, user=self.owner, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        self.team = SportsTeam.objects.create(group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.owner)
        self.player = SportsPlayer.objects.create(team=self.team, display_name="Analytics Batter", created_by=self.owner)
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Opponent",
            start_at=timezone.now() - timedelta(hours=2),
            status=SportsGame.Status.FINAL,
            runs_for=2,
            created_by=self.owner,
        )
        SoftballPlateAppearance.objects.create(
            game=self.game, player=self.player, sequence=1, inning=1,
            result=SoftballPlateAppearance.Result.SINGLE, runs_scored=1, created_by=self.owner,
        )
        SoftballPlateAppearance.objects.create(
            game=self.game, player=self.player, sequence=2, inning=2,
            result=SoftballPlateAppearance.Result.HOME_RUN, runs_scored=1, created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)

    def test_advanced_team_stats_returns_game_and_inning_pace(self):
        response = self.client.get(reverse("sports-advanced-team-stats", args=[self.team.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        analytics = response.data["inning_analytics"]
        self.assertEqual(analytics["games"], 1)
        self.assertEqual(analytics["runs"], 2)
        self.assertEqual(analytics["hits"], 2)
        self.assertEqual(analytics["avg_runs_per_game"], 2.0)
        self.assertEqual([row["inning"] for row in analytics["innings"]], [1, 2])
        self.assertEqual([row["hits"] for row in analytics["innings"]], [1, 1])
