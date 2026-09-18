from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.league_models import (
    LeagueDivision,
    LeagueGame,
    LeagueRosterEntry,
    LeagueSeason,
    LeagueTeamEntry,
    SportsOrganization,
    SportsOrganizationMembership,
)
from platform_sports.models import SportsGame, SportsTeam

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SYNCWORKS_FRONTEND_URL="https://syncworksapp.com",
)
class CommissionerCommandCenterTests(APITestCase):
    def setUp(self):
        self.commissioner = User.objects.create_user(
            username="commissioner",
            email="commissioner@example.com",
            password="pass12345",
        )
        self.group1 = SocialGroup.objects.create(
            name="Team One",
            kind=SocialGroup.Kind.TEAM,
            created_by=self.commissioner,
        )
        self.group2 = SocialGroup.objects.create(
            name="Team Two",
            kind=SocialGroup.Kind.TEAM,
            created_by=self.commissioner,
        )
        for group in (self.group1, self.group2):
            GroupMembership.objects.create(
                group=group,
                user=self.commissioner,
                role=GroupMembership.Role.OWNER,
                status=GroupMembership.Status.ACTIVE,
                invited_by=self.commissioner,
            )
        self.team1 = SportsTeam.objects.create(
            group=self.group1,
            sport=SportsTeam.Sport.SOFTBALL,
            created_by=self.commissioner,
        )
        self.team2 = SportsTeam.objects.create(
            group=self.group2,
            sport=SportsTeam.Sport.SOFTBALL,
            created_by=self.commissioner,
        )
        self.org = SportsOrganization.objects.create(
            name="Test Softball League",
            slug="test-softball-league",
            sport="SOFTBALL",
            created_by=self.commissioner,
        )
        SportsOrganizationMembership.objects.create(
            organization=self.org,
            user=self.commissioner,
            role=SportsOrganizationMembership.Role.COMMISSIONER,
            status=SportsOrganizationMembership.Status.ACTIVE,
            invited_by=self.commissioner,
        )
        self.season = LeagueSeason.objects.create(
            organization=self.org,
            name="Fall 2026",
            status=LeagueSeason.Status.ACTIVE,
            is_current=True,
            created_by=self.commissioner,
        )
        self.division = LeagueDivision.objects.create(
            season=self.season,
            name="Gold",
        )
        LeagueTeamEntry.objects.create(division=self.division, team=self.team1, status=LeagueTeamEntry.Status.ACTIVE, seed=1)
        LeagueTeamEntry.objects.create(division=self.division, team=self.team2, status=LeagueTeamEntry.Status.ACTIVE, seed=2)
        self.client.force_authenticate(self.commissioner)

    def test_round_robin_schedule_creates_mirrored_team_games_and_standings(self):
        response = self.client.post(
            reverse("sports-divisions-build-schedule", args=[self.division.id]),
            {
                "start_at": "2026-10-06T18:30:00-05:00",
                "fields": ["Field 1"],
                "slot_minutes": 60,
                "days_between_rounds": 7,
                "games_per_matchup": 1,
                "venue_name": "Dean Fain Park",
                "address_line1": "8700 Minnie Brown Rd",
                "city": "Montgomery",
                "state": "AL",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created"], 1)

        league_game = LeagueGame.objects.get(division=self.division)
        self.assertIsNotNone(league_game.home_sports_game_id)
        self.assertIsNotNone(league_game.away_sports_game_id)
        self.assertEqual(SportsGame.objects.filter(id__in=[league_game.home_sports_game_id, league_game.away_sports_game_id]).count(), 2)

        home_game = league_game.home_sports_game
        finish = self.client.post(
            reverse("sports-games-finish", args=[home_game.id]),
            {"runs_for": 12, "runs_against": 8},
            format="json",
        )
        self.assertEqual(finish.status_code, status.HTTP_200_OK)

        league_game.refresh_from_db()
        self.assertEqual(league_game.status, LeagueGame.Status.FINAL)
        self.assertEqual((league_game.home_score, league_game.away_score), (12, 8))

        standings = self.client.get(reverse("sports-divisions-standings", args=[self.division.id]))
        self.assertEqual(standings.status_code, status.HTTP_200_OK)
        self.assertEqual(standings.data["standings"][0]["wins"], 1)
        self.assertGreaterEqual(standings.data["standings"][0]["power_score"], 0)

    def test_player_email_invite_can_be_previewed_and_claimed(self):
        invite = self.client.post(
            reverse("sports-league-rosters-invite-email"),
            {
                "division": self.division.id,
                "team": self.team1.id,
                "email": "newplayer@example.com",
                "display_name": "New Player",
                "jersey_number": "17",
            },
            format="json",
        )
        self.assertEqual(invite.status_code, status.HTTP_201_CREATED)
        self.assertTrue(invite.data["email_sent"])
        self.assertIn("/sports/invite/", invite.data["invite_url"])

        roster = LeagueRosterEntry.objects.get(pk=invite.data["id"])
        token = str(roster.identity.claim_token)

        self.client.force_authenticate(user=None)
        preview = self.client.get(
            reverse("sports-league-rosters-invite-preview"),
            {"token": token, "roster": roster.id},
        )
        self.assertEqual(preview.status_code, status.HTTP_200_OK)
        self.assertEqual(preview.data["team_name"], "Team One")

        player_user = User.objects.create_user(
            username="newplayer",
            email="newplayer@example.com",
            password="pass12345",
        )
        self.client.force_authenticate(player_user)
        claim = self.client.post(
            reverse("sports-league-rosters-claim-token"),
            {"token": token, "roster": roster.id},
            format="json",
        )
        self.assertEqual(claim.status_code, status.HTTP_200_OK)
        roster.refresh_from_db()
        self.assertEqual(roster.status, LeagueRosterEntry.Status.ACTIVE)
        self.assertEqual(roster.sports_player.user_id, player_user.id)
        membership = GroupMembership.objects.get(group=self.group1, user=player_user)
        self.assertEqual(membership.status, GroupMembership.Status.ACTIVE)
