from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam

from .models import GameCastShare, SoftballPlayContext

User = get_user_model()


class AdvancedSoftballAnalyticsTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="analytics-owner",
            email="analytics-owner@example.com",
            password="pass12345",
        )
        self.member = User.objects.create_user(
            username="analytics-member",
            email="analytics-member@example.com",
            password="pass12345",
        )
        self.group = SocialGroup.objects.create(
            name="Quality Outs Softball",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.owner,
        )
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
            created_by=self.owner,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team,
            user=self.owner,
            display_name="Test Hitter",
            jersey_number="7",
            created_by=self.owner,
        )
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Visitors",
            start_at=timezone.now() - timedelta(hours=1),
            status=SportsGame.Status.LIVE,
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(
            game=self.game,
            player=self.player,
            batting_order=1,
            defensive_position="2B",
        )
        self.client.force_authenticate(user=self.owner)

    def _pa(self, sequence, result, *, outs=0, rbi=0):
        return SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.player,
            sequence=sequence,
            inning=1,
            result=result,
            outs_recorded=outs,
            rbi=rbi,
            created_by=self.owner,
        )

    def test_reach_average_sac_fly_quality_out_and_move_rate(self):
        self._pa(1, SoftballPlateAppearance.Result.SINGLE)
        self._pa(2, SoftballPlateAppearance.Result.WALK)
        sac = self._pa(3, SoftballPlateAppearance.Result.SAC_FLY, outs=1, rbi=1)
        productive = self._pa(4, SoftballPlateAppearance.Result.OUT, outs=1)
        empty_out = self._pa(5, SoftballPlateAppearance.Result.OUT, outs=1)

        SoftballPlayContext.objects.create(
            plate_appearance=sac,
            runner_on_third_before=True,
            runners_advanced=1,
            productive_out=True,
            batted_ball_type=SoftballPlayContext.BattedBallType.FLY,
            spray_zone=SoftballPlayContext.SprayZone.RIGHT_CENTER,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=productive,
            runner_on_second_before=True,
            runners_advanced=1,
            productive_out=True,
            batted_ball_type=SoftballPlayContext.BattedBallType.GROUND,
            spray_zone=SoftballPlayContext.SprayZone.RIGHT,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=empty_out,
            runner_on_first_before=True,
            runners_advanced=0,
            productive_out=False,
            batted_ball_type=SoftballPlayContext.BattedBallType.FLY,
            spray_zone=SoftballPlayContext.SprayZone.LEFT,
            created_by=self.owner,
        )

        response = self.client.get(reverse("sports-advanced-team-stats", args=[self.team.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.data["players"][0]

        # 1B + two ordinary outs = 3 AB. BB and SF are excluded from official AB.
        self.assertEqual(row["pa"], 5)
        self.assertEqual(row["ab"], 3)
        self.assertEqual(row["h"], 1)
        self.assertEqual(row["bb"], 1)
        self.assertEqual(row["sf"], 1)
        self.assertEqual(row["avg"], 0.333)

        # Reach AVG treats the walk as a successful reach while the sac fly stays neutral (0/0).
        self.assertEqual(row["reach_avg"], 0.5)

        # Hit + walk + sac fly + runner-advancing out = 4 quality PAs out of 5.
        self.assertEqual(row["quality_credits"], 4)
        self.assertEqual(row["quality_outs"], 2)
        self.assertEqual(row["qpa_pct"], 0.8)

        # There were three runner-move opportunities and two successful advances.
        self.assertEqual(row["move_opportunities"], 3)
        self.assertEqual(row["move_successes"], 2)
        self.assertEqual(row["move_rate"], 0.667)
        self.assertEqual(row["runners_advanced"], 2)
        self.assertEqual(row["spray"]["RIGHT_CENTER"], 1)
        self.assertEqual(row["spray"]["RIGHT"], 1)
        self.assertEqual(row["spray"]["LEFT"], 1)

    def test_player_card_returns_year_scope_and_spray_probabilities(self):
        first = self._pa(1, SoftballPlateAppearance.Result.SINGLE)
        second = self._pa(2, SoftballPlateAppearance.Result.OUT, outs=1)
        SoftballPlayContext.objects.create(
            plate_appearance=first,
            batted_ball_type=SoftballPlayContext.BattedBallType.LINE,
            spray_zone=SoftballPlayContext.SprayZone.RIGHT_CENTER,
            created_by=self.owner,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=second,
            batted_ball_type=SoftballPlayContext.BattedBallType.GROUND,
            spray_zone=SoftballPlayContext.SprayZone.RIGHT_CENTER,
            created_by=self.owner,
        )
        response = self.client.get(reverse("sports-player-card", args=[self.player.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["overall"]["ab"], 2)
        self.assertEqual(response.data["overall"]["h"], 1)
        self.assertEqual(response.data["overall"]["avg"], 0.5)
        self.assertEqual(response.data["splits"][0]["scope"], "LEAGUE")
        self.assertEqual(response.data["years"][0]["year"], self.game.start_at.year)
        self.assertEqual(response.data["tendencies"]["spray"][0]["zone"], "RIGHT_CENTER")
        self.assertEqual(response.data["tendencies"]["spray"][0]["pct"], 1.0)

    def test_manager_can_attach_context_to_existing_plate_appearance(self):
        pa = self._pa(1, SoftballPlateAppearance.Result.OUT, outs=1)
        response = self.client.post(
            reverse("sports-advanced-play-context"),
            {
                "plate_appearance": pa.id,
                "runner_on_second_before": True,
                "runners_advanced": 1,
                "productive_out": True,
                "batted_ball_type": "GROUND",
                "spray_zone": "INFIELD_RIGHT",
                "spray_x": "68.25",
                "spray_y": "34.50",
                "quality_note": "Moved runner to third",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        context = SoftballPlayContext.objects.get(plate_appearance=pa)
        self.assertTrue(context.productive_out)
        self.assertEqual(context.runners_advanced, 1)
        self.assertEqual(context.spray_zone, "INFIELD_RIGHT")

    def test_member_cannot_attach_manager_scoring_context(self):
        pa = self._pa(1, SoftballPlateAppearance.Result.OUT, outs=1)
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            reverse("sports-advanced-play-context"),
            {"plate_appearance": pa.id, "productive_out": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_private_gamecast_is_opt_in_but_token_is_public_when_enabled(self):
        settings_response = self.client.get(reverse("sports-gamecast-settings", args=[self.game.id]))
        self.assertEqual(settings_response.status_code, status.HTTP_200_OK)
        token = settings_response.data["token"]
        share = GameCastShare.objects.get(game=self.game)
        self.assertFalse(share.enabled)

        self.client.force_authenticate(user=None)
        disabled = self.client.get(reverse("sports-public-gamecast", args=[token]))
        self.assertEqual(disabled.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=self.owner)
        enabled = self.client.post(
            reverse("sports-gamecast-settings", args=[self.game.id]),
            {"enabled": True, "show_player_stats": True},
            format="json",
        )
        self.assertEqual(enabled.status_code, status.HTTP_200_OK)

        self._pa(1, SoftballPlateAppearance.Result.SINGLE)
        self.client.force_authenticate(user=None)
        public = self.client.get(reverse("sports-public-gamecast", args=[token]))
        self.assertEqual(public.status_code, status.HTTP_200_OK)
        self.assertEqual(public.data["game"]["team_name"], self.group.name)
        self.assertEqual(public.data["game"]["opponent_name"], "Visitors")
        self.assertEqual(len(public.data["plays"]), 1)
        self.assertIn("player_stats", public.data)
