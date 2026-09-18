from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsPlayer, SportsTeam
from platform_sports.ops_models import SportsPlayerProfile, TeamFee, TeamFeeAssignment
from platform_sports.views import sync_game_social_event

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SYNCWORKS_FRONTEND_URL="https://syncworksapp.com",
)
class PlayerTeamExperienceTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="coach",
            email="coach@example.com",
            password="pass12345",
        )
        self.group = SocialGroup.objects.create(
            name="Bed Springs Baptist",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.manager,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.manager,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.manager,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            league_name="Church League",
            division_name="Gold Division",
            created_by=self.manager,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team,
            display_name="Test Player",
            jersey_number="17",
            primary_position="SS",
            created_by=self.manager,
        )
        self.profile = SportsPlayerProfile.objects.create(
            player=self.player,
            email="player@example.com",
        )
        self.client.force_authenticate(self.manager)

    def test_new_user_receives_branded_email_and_can_claim_player_profile(self):
        response = self.client.post(
            reverse("sports-players-invite", args=[self.player.id]),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["email_sent"])
        self.assertFalse(response.data["account_found"])
        self.assertIn("/sports/team-invite/", response.data["invite_url"])
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("SYNCWORKS", html)
        self.assertIn("Personal", html)
        self.assertIn("Social", html)
        self.assertIn("Groups", html)
        self.assertIn("Business", html)

        token = response.data["invite_url"].rstrip("/").split("/")[-1]
        self.client.force_authenticate(user=None)
        preview = self.client.get(reverse("sports-players-invite-preview"), {"token": token})
        self.assertEqual(preview.status_code, status.HTTP_200_OK)
        self.assertEqual(preview.data["team_name"], "Bed Springs Baptist")

        player_user = User.objects.create_user(
            username="player",
            email="player@example.com",
            password="pass12345",
        )
        self.client.force_authenticate(player_user)
        claim = self.client.post(
            reverse("sports-players-claim-invite"),
            {"token": token},
            format="json",
        )
        self.assertEqual(claim.status_code, status.HTTP_200_OK)
        self.player.refresh_from_db()
        self.assertEqual(self.player.user_id, player_user.id)
        membership = GroupMembership.objects.get(group=self.group, user=player_user)
        self.assertEqual(membership.status, GroupMembership.Status.ACTIVE)

    def test_linked_player_can_edit_own_profile_and_player_center_is_private(self):
        player_user = User.objects.create_user(
            username="player2",
            email="player2@example.com",
            password="pass12345",
        )
        self.player.user = player_user
        self.player.save(update_fields=("user", "updated_at"))
        GroupMembership.objects.create(
            group=self.group,
            user=player_user,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.manager,
        )

        game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Vaughn Forest Church",
            start_at=timezone.now() + timedelta(days=4),
            venue_name="Dean Fain Park",
            address_line1="8700 Minnie Brown Rd",
            city="Montgomery",
            state="AL",
            created_by=self.manager,
        )
        event = sync_game_social_event(game)
        event.flyer_url = "https://example.com/game-flyer.jpg"
        event.save(update_fields=("flyer_url", "updated_at"))

        fee = TeamFee.objects.create(
            team=self.team,
            title="League fee",
            amount_cents=5000,
            created_by=self.manager,
        )
        TeamFeeAssignment.objects.create(
            fee=fee,
            player=self.player,
            amount_cents=5000,
            updated_by=self.manager,
        )

        self.client.force_authenticate(player_user)
        update = self.client.patch(
            reverse("sports-player-profiles-detail", args=[self.profile.id]),
            {"phone": "334-555-0101", "emergency_contact_name": "Family"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["phone"], "334-555-0101")

        center = self.client.get(reverse("sports-teams-player-center", args=[self.team.id]))
        self.assertEqual(center.status_code, status.HTTP_200_OK)
        self.assertEqual(center.data["player"]["id"], self.player.id)
        self.assertEqual(center.data["balance_cents"], 5000)
        self.assertEqual(center.data["next_game"]["opponent_name"], "Vaughn Forest Church")
        self.assertEqual(
            center.data["next_game"]["social_event_detail"]["flyer_url"],
            "https://example.com/game-flyer.jpg",
        )
