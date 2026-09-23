from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam,
)

User = get_user_model()


class PlayerBookAuditTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(username="auditcoach", email="auditcoach@example.test", password="x")
        self.owner = User.objects.create_user(username="auditowner", email="auditowner@example.test", password="x")
        self.teammate = User.objects.create_user(username="auditteammate", email="auditteammate@example.test", password="x")
        self.group = SocialGroup.objects.create(
            name="Audit Test Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        for person, role in (
            (self.coach, GroupMembership.Role.OWNER),
            (self.owner, GroupMembership.Role.MEMBER),
            (self.teammate, GroupMembership.Role.MEMBER),
        ):
            GroupMembership.objects.create(
                group=self.group, user=person, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
            )
        self.team = SportsTeam.objects.create(
            group=self.group, sport="SOFTBALL", created_by=self.coach
        )
        self.player = SportsPlayer.objects.create(
            team=self.team, user=self.owner, display_name="Example Shortstop",
            jersey_number="7", created_by=self.coach,
        )
        self.first = SportsGame.objects.create(
            team=self.team, opponent_name="One", start_at=timezone.now(),
            status=SportsGame.Status.FINAL, runs_for=10, runs_against=9, created_by=self.coach,
        )
        self.second = SportsGame.objects.create(
            team=self.team, opponent_name="Two", start_at=timezone.now(),
            status=SportsGame.Status.FINAL, runs_for=27, runs_against=12, created_by=self.coach,
        )
        for game in (self.first, self.second):
            SportsLineupSpot.objects.create(
                game=game, player=self.player, batting_order=1,
                defensive_position="SS", is_starter=True,
            )
        SoftballPlateAppearance.objects.create(
            game=self.first, player=self.player, sequence=1, inning=1,
            result=SoftballPlateAppearance.Result.SINGLE, runs_scored=0,
            rbi=1, outs_recorded=0, created_by=self.coach,
        )

    def test_owner_and_coach_see_source_gaps_without_fake_statistics(self):
        path = f"/api/v1/sports/players/{self.player.id}/book-audit/"
        self.client.force_authenticate(self.owner)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data)
        by_game = {row["game_id"]: row for row in response.data["games"]}
        self.assertEqual(by_game[self.first.id]["status"], "SOURCE_NOT_UPLOADED")
        self.assertEqual(by_game[self.first.id]["hits_recorded"], 1)
        self.assertEqual(by_game[self.second.id]["status"], "MISSING_PLAYS")
        self.assertEqual(by_game[self.second.id]["appearance_count"], 0)
        self.assertEqual(response.data["games_needing_review"], 2)
        self.client.force_authenticate(self.teammate)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_authenticate(self.coach)
        self.assertEqual(self.client.get(path).status_code, 200)
