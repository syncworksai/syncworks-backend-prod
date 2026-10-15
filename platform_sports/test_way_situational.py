from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup

from .models import SportsPlayer, SportsTeam
from .way_models import SportsPlayerSituationalSplit


User = get_user_model()


class WaySituationalApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="situational-owner", password="pass12345")
        self.member = User.objects.create_user(username="situational-member", password="pass12345")
        self.group = SocialGroup.objects.create(name="Situational Test", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            badge_rules={"way_we_play_enabled": True},
            created_by=self.owner,
        )
        self.one = SportsPlayer.objects.create(team=self.team, display_name="One", created_by=self.owner)
        self.two = SportsPlayer.objects.create(team=self.team, display_name="Two", created_by=self.owner)
        SportsPlayerSituationalSplit.objects.create(
            team=self.team,
            player=self.one,
            season_name="Fall 2026",
            sample_games=6,
            bases_empty_hits=4,
            bases_empty_ab=5,
            two_out_hits=3,
            two_out_ab=4,
            runners_on_hits=6,
            runners_on_ab=8,
        )
        SportsPlayerSituationalSplit.objects.create(
            team=self.team,
            player=self.two,
            season_name="Fall 2026",
            sample_games=6,
            bases_empty_hits=2,
            bases_empty_ab=5,
            two_out_hits=1,
            two_out_ab=4,
            runners_on_hits=2,
            runners_on_ab=8,
        )

    def test_member_can_read_team_rates_and_sit_plus(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(reverse("sports-way-situational-detail", args=[self.team.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["can_manage"])
        self.assertEqual(response.data["sample_games"], 6)
        self.assertEqual(response.data["team"]["bases_empty"]["h"], 6)
        self.assertEqual(response.data["team"]["bases_empty"]["ab"], 10)
        self.assertEqual(response.data["team"]["bases_empty"]["rate"], 0.6)
        self.assertEqual(response.data["team"]["two_out"]["rate"], 0.5)
        self.assertEqual(response.data["team"]["runners_on"]["rate"], 0.5)
        one = next(row for row in response.data["rows"] if row["player"]["id"] == self.one.id)
        two = next(row for row in response.data["rows"] if row["player"]["id"] == self.two.id)
        self.assertGreater(one["situational_index"], 100)
        self.assertLess(two["situational_index"], 100)
        self.assertEqual(one["bases_empty"]["rate"], 0.8)
        self.assertEqual(one["bases_empty"]["h"], 4)
        self.assertEqual(one["bases_empty"]["ab"], 5)

    def test_member_cannot_edit_but_owner_can(self):
        url = reverse("sports-way-situational-save-player", args=[self.team.id])
        payload = {
            "player": self.one.id,
            "sample_games": 6,
            "bases_empty_hits": 5,
            "bases_empty_ab": 6,
            "two_out_hits": 4,
            "two_out_ab": 5,
            "runners_on_hits": 7,
            "runners_on_ab": 9,
        }
        self.client.force_authenticate(user=self.member)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["saved"])
        row = SportsPlayerSituationalSplit.objects.get(team=self.team, player=self.one, season_name="Fall 2026")
        self.assertEqual(row.bases_empty_hits, 5)
        self.assertEqual(row.runners_on_ab, 9)
