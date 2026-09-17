from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import EventMemberResponse, GroupMembership, SocialEvent, SocialGroup
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam

User = get_user_model()


class TeamAvailabilityLineupTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="avail-manager", email="avail-manager@example.com", password="x")
        self.player_user = User.objects.create_user(username="avail-player", email="avail-player@example.com", password="x")
        self.group = SocialGroup.objects.create(name="Availability Team", kind=SocialGroup.Kind.TEAM, created_by=self.manager)
        GroupMembership.objects.create(group=self.group, user=self.manager, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.manager)
        GroupMembership.objects.create(group=self.group, user=self.player_user, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=self.manager)
        self.team = SportsTeam.objects.create(group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.manager)
        self.player = SportsPlayer.objects.create(team=self.team, user=self.player_user, display_name="Linked Player", created_by=self.manager)
        self.event = SocialEvent.objects.create(organizer_group=self.group, created_by=self.manager, title="Game", start_at=timezone.now(), status=SocialEvent.Status.PUBLISHED)
        self.game = SportsGame.objects.create(team=self.team, social_event=self.event, opponent_name="Opponent", start_at=timezone.now(), created_by=self.manager)
        self.response = EventMemberResponse.objects.create(event=self.event, group=self.group, user=self.player_user, response=EventMemberResponse.Response.NO)

    def test_out_player_cannot_be_saved_to_lineup(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            reverse("sports-games-set-lineup", args=[self.game.id]),
            {"spots": [{"player": self.player.id, "batting_order": 1, "defensive_position": "2B", "is_starter": True}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("OUT", response.data["detail"])

    def test_changing_confirmation_to_out_removes_saved_lineup_spot(self):
        self.response.response = EventMemberResponse.Response.YES
        self.response.save(update_fields=("response", "updated_at"))
        SportsLineupSpot.objects.create(game=self.game, player=self.player, batting_order=1, defensive_position="2B")

        self.client.force_authenticate(self.player_user)
        response = self.client.patch(
            reverse("social-event-responses-detail", args=[self.response.id]),
            {"response": "NO"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(SportsLineupSpot.objects.filter(game=self.game, player=self.player).exists())
