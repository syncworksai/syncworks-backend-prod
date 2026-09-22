from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsPlayer, SportsTeam
from platform_sports.ops_models import SportsPlayerProfile

User = get_user_model()


class TeamInviteSelfJoinV7Tests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner-invites@example.com",
            email="owner-invites@example.com",
            password="test-pass-123",
        )
        self.member = User.objects.create_user(
            username="member-invites@example.com",
            email="member-invites@example.com",
            first_name="Roster",
            last_name="Player",
            password="test-pass-123",
        )
        self.group = SocialGroup.objects.create(
            name="Bed Springs Baptist",
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
        self.membership = GroupMembership.objects.create(
            group=self.group,
            user=self.member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            created_by=self.owner,
        )
        self.url = "/api/v1/sports/players/join-mine/"
        self.client.force_authenticate(self.member)

    def test_exact_email_claims_existing_roster_without_losing_player_id(self):
        player = SportsPlayer.objects.create(
            team=self.team,
            display_name="Roster Player",
            jersey_number="7",
            created_by=self.owner,
        )
        SportsPlayerProfile.objects.create(player=player, email=self.member.email.upper())
        response = self.client.post(self.url, {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["matched_existing"])
        self.assertEqual(response.data["player"]["id"], player.id)
        player.refresh_from_db()
        self.assertEqual(player.user_id, self.member.id)
        self.assertEqual(player.jersey_number, "7")
        self.assertEqual(SportsPlayer.objects.filter(team=self.team).count(), 1)
        again = self.client.post(self.url, {"team": self.team.id}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.data["already_linked"])
        self.assertEqual(SportsPlayer.objects.filter(team=self.team).count(), 1)

    def test_unmatched_active_member_can_add_themselves(self):
        response = self.client.post(self.url, {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["matched_existing"])
        player = SportsPlayer.objects.get(team=self.team, user=self.member)
        self.assertEqual(player.display_name, "Roster Player")
        self.assertEqual(player.manager_profile.email, self.member.email)

    def test_pending_or_nonmember_cannot_join_roster(self):
        self.membership.status = GroupMembership.Status.REQUESTED
        self.membership.save(update_fields=("status", "updated_at"))
        self.assertEqual(self.client.post(self.url, {"team": self.team.id}, format="json").status_code, 403)
        self.membership.delete()
        self.assertEqual(self.client.post(self.url, {"team": self.team.id}, format="json").status_code, 403)
        self.assertFalse(SportsPlayer.objects.filter(team=self.team).exists())

    def test_ambiguous_email_requires_manager_review(self):
        for number in ("10", "11"):
            player = SportsPlayer.objects.create(
                team=self.team,
                display_name=f"Player {number}",
                jersey_number=number,
                created_by=self.owner,
            )
            SportsPlayerProfile.objects.create(player=player, email=self.member.email)
        response = self.client.post(self.url, {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(SportsPlayer.objects.filter(team=self.team, user=self.member).exists())

    def test_email_of_another_linked_player_requires_manager_review(self):
        linked_user = User.objects.create_user(
            username="other-invites@example.com",
            email="other-invites@example.com",
            password="test-pass-123",
        )
        player = SportsPlayer.objects.create(
            team=self.team,
            user=linked_user,
            display_name="Other Player",
            created_by=self.owner,
        )
        SportsPlayerProfile.objects.create(player=player, email=self.member.email)
        response = self.client.post(self.url, {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SportsPlayer.objects.filter(team=self.team).count(), 1)
