from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from .models import SoftballPlayContext

User = get_user_model()


class TeamSituationSplitsTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="situation-coach", email="situation-coach@example.test", password="x"
        )
        self.scorer = User.objects.create_user(
            username="situation-scorer", email="situation-scorer@example.test", password="x"
        )
        self.outsider = User.objects.create_user(
            username="situation-outsider", email="situation-outsider@example.test", password="x"
        )
        self.group = SocialGroup.objects.create(
            name="Situations Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        for user, role in (
            (self.coach, GroupMembership.Role.OWNER),
            (self.scorer, GroupMembership.Role.SCOREKEEPER),
        ):
            GroupMembership.objects.create(
                group=self.group, user=user, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
            )
        self.team = SportsTeam.objects.create(group=self.group, sport="SOFTBALL", created_by=self.coach)
        self.player = SportsPlayer.objects.create(
            team=self.team, display_name="Example Batter", created_by=self.coach,
        )
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Example", start_at=timezone.now(),
            created_by=self.coach, status=SportsGame.Status.FINAL, runs_for=2,
        )
        self.a = SoftballPlateAppearance.objects.create(
            game=self.game, player=self.player, sequence=1, inning=1,
            result="1B", rbi=1, created_by=self.coach,
        )
        self.b = SoftballPlateAppearance.objects.create(
            game=self.game, player=self.player, sequence=2, inning=2,
            result="SF", rbi=1, runs_scored=1, created_by=self.coach,
        )
        self.c = SoftballPlateAppearance.objects.create(
            game=self.game, player=self.player, sequence=3, inning=3,
            result="OUT", outs_recorded=1, created_by=self.coach,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=self.a, created_by=self.coach,
            outs_before=2, runner_on_second_before=True, runners_advanced=1,
        )
        SoftballPlayContext.objects.create(
            plate_appearance=self.b, created_by=self.coach,
            outs_before=1, runner_on_third_before=True, runners_advanced=1, productive_out=True,
        )

    def test_rate_splits_are_precise_and_missing_outs_not_guessed(self):
        self.client.force_authenticate(self.coach)
        result = self.client.get(f"/api/v1/sports/advanced/teams/{self.team.id}/situations/")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["tracked_appearances"], 2)
        self.assertEqual(result.data["excluded_missing_outs_context"], 1)
        two_outs = result.data["splits"]["2_OUTS"]
        self.assertEqual((two_outs["h"], two_outs["ab"], two_outs["avg"]), (1, 1, 1.0))
        sac = result.data["objectives"]["SAC_FLY"]
        self.assertEqual((sac["attempts"], sac["successes"]), (1, 1))
        move = result.data["objectives"]["MOVE_RUNNER"]
        self.assertEqual((move["attempts"], move["successes"]), (2, 2))

    def test_authorized_scorekeeper_can_record_outs_context(self):
        self.client.force_authenticate(self.scorer)
        response = self.client.post("/api/v1/sports/advanced/play-context/", {
            "plate_appearance": self.c.id, "outs_before": 2,
            "runner_on_first_before": True, "runners_advanced": 1,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        split = self.client.get(f"/api/v1/sports/advanced/teams/{self.team.id}/situations/")
        self.assertEqual(split.data["tracked_appearances"], 3)
        self.assertEqual(split.data["splits"]["2_OUTS"]["pa"], 2)
        self.client.force_authenticate(self.outsider)
        denied = self.client.get(f"/api/v1/sports/advanced/teams/{self.team.id}/situations/")
        self.assertEqual(denied.status_code, 403)
