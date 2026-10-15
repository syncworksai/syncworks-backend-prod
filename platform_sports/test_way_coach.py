from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup

from .models import SportsPlayer, SportsTeam
from .way_models import SportsPlayerCoachSnapshot, SportsPlayerExecutionTotal, SportsPlayerSituationalSplit


User = get_user_model()


class WayCoachApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="coach-owner", password="pass12345")
        self.member = User.objects.create_user(username="coach-player", password="pass12345")
        self.other = User.objects.create_user(username="coach-other", password="pass12345")
        self.group = SocialGroup.objects.create(name="Coach Box Test", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(group=self.group, user=self.owner, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        GroupMembership.objects.create(group=self.group, user=self.member, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            badge_rules={"way_we_play_enabled": True},
            created_by=self.owner,
        )
        self.jordan = SportsPlayer.objects.create(team=self.team, display_name="Jordan Test", user=self.member, created_by=self.owner)
        self.depth = SportsPlayer.objects.create(team=self.team, display_name="Depth Test", created_by=self.owner)
        SportsPlayerSituationalSplit.objects.create(
            team=self.team,
            player=self.jordan,
            season_name="Fall 2026",
            sample_games=6,
            batting_sample_games=8,
            batting_hits=15,
            batting_ab=21,
            bases_empty_hits=1,
            bases_empty_ab=2,
            two_out_hits=2,
            two_out_ab=3,
            runners_on_hits=7,
            runners_on_ab=9,
        )
        SportsPlayerSituationalSplit.objects.create(
            team=self.team,
            player=self.depth,
            season_name="Fall 2026",
            sample_games=6,
            batting_sample_games=8,
            batting_hits=5,
            batting_ab=20,
            bases_empty_hits=1,
            bases_empty_ab=5,
            two_out_hits=1,
            two_out_ab=5,
            runners_on_hits=2,
            runners_on_ab=10,
        )
        SportsPlayerExecutionTotal.objects.create(
            team=self.team,
            player=self.jordan,
            season_name="Fall 2026",
            points=Decimal("10"),
            opportunities=15,
            updated_by=self.owner,
        )
        SportsPlayerExecutionTotal.objects.create(
            team=self.team,
            player=self.depth,
            season_name="Fall 2026",
            points=Decimal("5"),
            opportunities=15,
            updated_by=self.owner,
        )

    def test_manager_gets_clear_lineup_bands_and_two_sided_impact(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse("sports-way-coach-detail", args=[self.team.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["can_manage"])
        self.assertEqual(len(response.data["rows"]), 2)
        jordan = next(row for row in response.data["rows"] if row["player"]["id"] == self.jordan.id)
        self.assertEqual(jordan["recommended_role"], "Run producer")
        self.assertEqual(jordan["recommended_slots"], "4-7")
        self.assertIn(jordan["lineup_band"]["key"], {"TOP", "MIDDLE", "LOWER"})
        self.assertIn("projected_runs_per_game_low", jordan["focus"])
        self.assertIn("projected_events_per_10_games", jordan["focus"])
        self.assertGreaterEqual(jordan["focus"]["projected_runs_per_game_high"], jordan["focus"]["projected_runs_per_game_low"])
        self.assertIsNotNone(jordan["downside"])
        self.assertEqual(jordan["downside"]["drop"], 0.05)
        self.assertIn("projected_runs_lost_per_game_high", jordan["downside"])
        self.assertIn("SIT+ measures situational hitting", jordan["player_message"])
        self.assertIn("sit_plus", response.data["metric_distinction"])
        self.assertEqual(len(response.data["suggested_order"]), 2)
        self.assertEqual(response.data["suggested_order"][0]["lineup_band"]["key"], "TOP")

    def test_member_sees_only_own_development_analysis_and_no_coach_note(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post(reverse("sports-way-coach-snapshot", args=[self.team.id]), {}, format="json")
        self.client.post(
            reverse("sports-way-coach-save-player", args=[self.team.id]),
            {
                "player": self.jordan.id,
                "role_override": "Middle-order anchor",
                "slots_override": "3-4",
                "focus_override": "TWO_OUT",
                "coach_note": "Private coach note",
            },
            format="json",
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.get(reverse("sports-way-coach-detail", args=[self.team.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["can_manage"])
        self.assertEqual(len(response.data["rows"]), 1)
        row = response.data["rows"][0]
        self.assertEqual(row["player"]["id"], self.jordan.id)
        self.assertEqual(row["effective_role"], "Middle-order anchor")
        self.assertEqual(row["coach_note"], "")
        self.assertIn(row["lineup_band"]["key"], {"TOP", "MIDDLE", "LOWER"})
        self.assertTrue(row["player_message"])
        self.assertEqual(response.data["suggested_order"], [])

    def test_manager_can_snapshot_and_override_weekly_plan(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse("sports-way-coach-snapshot", args=[self.team.id]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(SportsPlayerCoachSnapshot.objects.filter(team=self.team).count(), 2)

        response = self.client.post(
            reverse("sports-way-coach-save-player", args=[self.team.id]),
            {
                "player": self.jordan.id,
                "role_override": "Middle-order anchor",
                "slots_override": "3-4",
                "focus_override": "TWO_OUT",
                "coach_note": "Protect the inning and pass the torch.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        saved = response.data["saved"]
        self.assertEqual(saved["effective_role"], "Middle-order anchor")
        self.assertEqual(saved["effective_slots"], "3-4")
        self.assertEqual(saved["focus"]["key"], "TWO_OUT")
        self.assertEqual(saved["coach_note"], "Protect the inning and pass the torch.")
        snapshot = SportsPlayerCoachSnapshot.objects.get(team=self.team, player=self.jordan)
        self.assertEqual(snapshot.focus_override, "TWO_OUT")
        self.assertIn("lineup_band", snapshot.metrics)
