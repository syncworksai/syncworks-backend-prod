from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup

from .models import SportsPlayer, SportsTeam
from .ops_models import SportsPlayerProfile, TeamFeeAssignment


User = get_user_model()


class SportsManagerOpsApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="ops-owner", email="ops-owner@example.com", password="pass12345")
        self.member = User.objects.create_user(username="ops-member", email="ops-member@example.com", password="pass12345")
        self.other = User.objects.create_user(username="ops-other", email="ops-other@example.com", password="pass12345")
        self.group = SocialGroup.objects.create(name="Ops Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        for user, role in ((self.owner, GroupMembership.Role.OWNER), (self.member, GroupMembership.Role.MEMBER), (self.other, GroupMembership.Role.MEMBER)):
            GroupMembership.objects.create(group=self.group, user=user, role=role, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        self.team = SportsTeam.objects.create(group=self.group, sport=SportsTeam.Sport.SOFTBALL, season_name="Fall 2026", created_by=self.owner)
        self.member_player = SportsPlayer.objects.create(team=self.team, user=self.member, display_name="Member Player", jersey_number="7", created_by=self.owner)
        self.other_player = SportsPlayer.objects.create(team=self.team, user=self.other, display_name="Other Player", jersey_number="2", created_by=self.owner)
        self.client.force_authenticate(user=self.owner)

    def test_manager_can_create_fee_and_assign_roster_but_player_only_sees_self(self):
        response = self.client.post(reverse("sports-team-fees-list"), {"team": self.team.id, "title": "League fee", "amount_cents": 5000}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        fee_id = response.data["id"]
        assign = self.client.post(reverse("sports-team-fees-assign-roster", args=[fee_id]), {}, format="json")
        self.assertEqual(assign.status_code, status.HTTP_200_OK)
        self.assertEqual(TeamFeeAssignment.objects.filter(fee_id=fee_id).count(), 2)

        self.client.force_authenticate(user=self.member)
        mine = self.client.get(reverse("sports-fee-assignments-list"), {"team": self.team.id})
        self.assertEqual(mine.status_code, status.HTTP_200_OK)
        rows = mine.data if isinstance(mine.data, list) else mine.data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player"], self.member_player.id)

    def test_player_profile_contact_is_private_to_manager_and_that_player(self):
        SportsPlayerProfile.objects.create(player=self.other_player, email="private@example.com", phone="555-0100")
        manager = self.client.get(reverse("sports-player-profiles-list"), {"team": self.team.id})
        self.assertEqual(manager.status_code, status.HTTP_200_OK)
        manager_rows = manager.data if isinstance(manager.data, list) else manager.data["results"]
        self.assertEqual(len(manager_rows), 1)

        self.client.force_authenticate(user=self.member)
        member = self.client.get(reverse("sports-player-profiles-list"), {"team": self.team.id})
        self.assertEqual(member.status_code, status.HTTP_200_OK)
        member_rows = member.data if isinstance(member.data, list) else member.data["results"]
        self.assertEqual(member_rows, [])

    def test_manual_stats_feed_scope_summary(self):
        response = self.client.post(reverse("sports-stat-ledger-list"), {
            "team": self.team.id,
            "player": self.member_player.id,
            "season_name": "Fall 2026",
            "scope": "LEAGUE",
            "games": 2,
            "pa": 8,
            "ab": 7,
            "hits": 4,
            "doubles": 1,
            "triples": 0,
            "home_runs": 1,
            "walks": 1,
            "sac_flies": 0,
            "rbi": 3,
            "runs": 2,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        summary = self.client.get(reverse("sports-stat-ledger-summary"), {"team": self.team.id, "scope": "LEAGUE"})
        self.assertEqual(summary.status_code, status.HTTP_200_OK)
        row = next(item for item in summary.data["rows"] if item["player"]["id"] == self.member_player.id)
        self.assertEqual(row["g"], 2)
        self.assertEqual(row["h"], 4)
        self.assertEqual(row["hr"], 1)
        self.assertEqual(row["rbi"], 3)
