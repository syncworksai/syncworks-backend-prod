from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.league_models import SoftballRuleSet, SportsOrganization
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam

User = get_user_model()


class GameBookRulesTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="book-manager", email="book-manager@example.com", password="x")
        self.group = SocialGroup.objects.create(name="Book Team", kind=SocialGroup.Kind.TEAM, created_by=self.manager)
        GroupMembership.objects.create(group=self.group, user=self.manager, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.manager)
        self.team = SportsTeam.objects.create(group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.manager)
        self.player = SportsPlayer.objects.create(team=self.team, display_name="Slugger", created_by=self.manager)
        self.organization = SportsOrganization.objects.create(name="Test League", slug="test-league-book", sport="SOFTBALL", created_by=self.manager)
        self.rules = SoftballRuleSet.objects.create(organization=self.organization, name="1 HR", home_run_rule=SoftballRuleSet.HomeRunRule.FIXED, home_run_limit=1, created_by=self.manager)
        self.game = SportsGame.objects.create(team=self.team, opponent_name="Opponent", start_at=timezone.now(), created_by=self.manager, rule_set=self.rules)
        SportsLineupSpot.objects.create(game=self.game, player=self.player, batting_order=1, defensive_position="MM")
        self.client.force_authenticate(self.manager)
        self.client.post(reverse("sports-games-start", args=[self.game.id]), {}, format="json")

    def test_fixed_home_run_limit_is_enforced(self):
        first = self.client.post(reverse("sports-games-play", args=[self.game.id]), {"result":"HR","runs_scored":1,"rbi":1}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(reverse("sports-games-play", args=[self.game.id]), {"result":"HR","runs_scored":1,"rbi":1}, format="json")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("cap", second.data["detail"].lower())

    def test_opponent_inning_line_updates_score(self):
        response = self.client.post(reverse("sports-games-inning-line", args=[self.game.id]), {"inning":1,"opponent_runs":3,"opponent_hits":4}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.game.refresh_from_db()
        self.assertEqual(self.game.runs_against, 3)
