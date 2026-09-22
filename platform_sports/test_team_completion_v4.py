from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsTeam


User = get_user_model()


class TeamCompletionQueueTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="manager@example.com", password="test-pass-123")
        self.group = SocialGroup.objects.create(
            name="Completion Team",
            kind=SocialGroup.Kind.TEAM,
            category=SocialGroup.Category.SPORTS,
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
        self.old = SportsGame.objects.create(
            team=self.team,
            opponent_name="Old Opponent",
            start_at=timezone.now() - timedelta(days=2),
            status=SportsGame.Status.SCHEDULED,
            created_by=self.owner,
        )
        self.future = SportsGame.objects.create(
            team=self.team,
            opponent_name="Future Opponent",
            start_at=timezone.now() + timedelta(days=2),
            status=SportsGame.Status.SCHEDULED,
            created_by=self.owner,
        )

    def test_dashboard_separates_past_unfinished_games(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/api/v1/sports/teams/{self.team.id}/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["needs_completion_games"]], [self.old.id])
        self.assertEqual([row["id"] for row in response.data["upcoming_games"]], [self.future.id])

    def test_manager_can_complete_scheduled_game_later(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/sports/games/{self.old.id}/finish/",
            {"runs_for": 12, "runs_against": 8},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], SportsGame.Status.FINAL)
        self.assertEqual(response.data["runs_for"], 12)
        self.assertEqual(response.data["runs_against"], 8)
