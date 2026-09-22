from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupFollow, GroupInviteLink, GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam, SoftballPlateAppearance
from platform_sports.ops_models import SoftballStatLedgerEntry, SportsPlayerProfile, TeamFee, TeamFeeAssignment

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SYNCWORKS_FRONTEND_URL="https://syncworksapp.com",
)
class TeamFansPasswordMergeV8Tests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="v8-owner@example.com",
            email="v8-owner@example.com", password="test-password-123",
        )
        self.manager = User.objects.create_user(
            username="v8-manager@example.com",
            email="v8-manager@example.com", password="test-password-123",
        )
        self.player = User.objects.create_user(
            username="v8-player@example.com",
            email="v8-player@example.com",
            first_name="New", last_name="Player",
            password="test-password-123",
        )
        self.fan = User.objects.create_user(
            username="v8-fan@example.com",
            email="v8-fan@example.com", password="test-password-123",
        )
        self.group = SocialGroup.objects.create(
            name="Bed Springs V8 Test",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            category=SocialGroup.Category.SPORTS,
            allow_followers=True,
            player_join_password_hash=make_password("BSB26"),
            created_by=self.owner,
        )
        for user, role in ((self.owner, GroupMembership.Role.OWNER), (self.manager, GroupMembership.Role.MANAGER)):
            GroupMembership.objects.create(
                group=self.group, user=user, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.owner,
            )
        self.link = GroupInviteLink.objects.create(
            group=self.group, role=GroupMembership.Role.MEMBER, created_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)

    def test_creator_can_change_player_password_but_manager_cannot(self):
        self.client.force_authenticate(self.manager)
        denied = self.client.post(
            f"/api/v1/social/groups/{self.group.id}/player-password/",
            {"password": "OTHER"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.owner)
        changed = self.client.post(
            f"/api/v1/social/groups/{self.group.id}/player-password/",
            {"password": "NEWPASS"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(changed.data["has_player_join_password"])
        self.group.refresh_from_db()
        self.assertNotEqual(self.group.player_join_password_hash, "NEWPASS")

    def test_player_password_gates_membership_and_keeps_roles_separate(self):
        self.client.force_authenticate(self.player)
        wrong = self.client.post(
            "/api/v1/social/group-invite-links/join-player/",
            {"token": str(self.link.token), "password": "WRONG"},
            format="json",
        )
        self.assertEqual(wrong.status_code, 403)
        self.assertFalse(GroupMembership.objects.filter(group=self.group, user=self.player).exists())
        joined = self.client.post(
            "/api/v1/social/group-invite-links/join-player/",
            {"token": str(self.link.token), "password": "BSB26"},
            format="json",
        )
        self.assertEqual(joined.status_code, 200)
        membership = GroupMembership.objects.get(group=self.group, user=self.player)
        self.assertEqual(membership.status, GroupMembership.Status.ACTIVE)
        self.assertEqual(membership.role, GroupMembership.Role.MEMBER)
        self.assertFalse(SportsPlayer.objects.filter(team=self.team, user=self.player).exists())
        add = self.client.post(
            "/api/v1/sports/players/join-mine/",
            {"team": self.team.id}, format="json",
        )
        self.assertEqual(add.status_code, 201)
        self.assertTrue(SportsPlayer.objects.filter(team=self.team, user=self.player).exists())

    def test_fan_can_follow_private_invite_without_player_password_and_unsubscribe(self):
        self.client.force_authenticate(self.fan)
        response = self.client.post(
            "/api/v1/social/group-invite-links/follow-fan/",
            {"token": str(self.link.token), "email_updates": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(GroupFollow.objects.get(group=self.group, user=self.fan).gamecast_email_updates)
        self.assertFalse(GroupMembership.objects.filter(group=self.group, user=self.fan).exists())
        self.client.force_authenticate(user=None)
        feed = self.client.get(
            "/api/v1/social/group-invite-links/fan-feed/",
            {"token": str(self.link.token)},
        )
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(feed.data["group"]["name"], self.group.name)
        self.client.force_authenticate(self.fan)
        turned_off = self.client.post(
            "/api/v1/social/group-invite-links/follow-fan/",
            {"token": str(self.link.token), "email_updates": False},
            format="json",
        )
        self.assertEqual(turned_off.status_code, 200)
        self.assertFalse(GroupFollow.objects.get(group=self.group, user=self.fan).gamecast_email_updates)
        gone = self.client.post(
            "/api/v1/social/group-invite-links/unfollow-fan/",
            {"token": str(self.link.token)}, format="json",
        )
        self.assertEqual(gone.status_code, 200)
        self.assertFalse(GroupFollow.objects.filter(group=self.group, user=self.fan).exists())

    def test_gamecast_emails_only_opted_in_fans_and_only_once(self):
        GroupFollow.objects.create(group=self.group, user=self.fan, gamecast_email_updates=True)
        game = SportsGame.objects.create(
            team=self.team, opponent_name="Test Opponent",
            start_at=timezone.now(), created_by=self.owner,
        )
        starter = SportsPlayer.objects.create(
            team=self.team, display_name="Starter", created_by=self.owner,
        )
        SportsLineupSpot.objects.create(
            game=game, player=starter, batting_order=1, defensive_position="2B",
        )
        started = self.client.post(f"/api/v1/sports/games/{game.id}/start/", {}, format="json")
        self.assertEqual(started.status_code, 200)
        mail.outbox.clear()
        activated = self.client.post(
            f"/api/v1/sports/games/{game.id}/gamecast/",
            {"enabled": True}, format="json",
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].bcc, [self.fan.email])
        self.assertEqual(mail.outbox[0].to, [])
        self.assertIn(f"/gamecast/{game.gamecast_token}", mail.outbox[0].body)
        again = self.client.post(
            f"/api/v1/sports/games/{game.id}/gamecast/",
            {"enabled": True}, format="json",
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_manager_link_by_member_id_requires_active_membership(self):
        original = SportsPlayer.objects.create(
            team=self.team, display_name="Manual Entry", created_by=self.owner,
        )
        self.client.force_authenticate(self.manager)
        blocked = self.client.post(
            f"/api/v1/sports/players/{original.id}/link-member/",
            {"user": self.player.id}, format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        GroupMembership.objects.create(
            group=self.group, user=self.player, role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.owner,
        )
        linked = self.client.post(
            f"/api/v1/sports/players/{original.id}/link-member/",
            {"user": self.player.id}, format="json",
        )
        self.assertEqual(linked.status_code, 200)
        original.refresh_from_db()
        self.assertEqual(original.user_id, self.player.id)
        self.assertEqual(original.manager_profile.email, self.player.email)

    def test_merge_moves_stats_and_dues_and_archives_source(self):
        primary = SportsPlayer.objects.create(
            team=self.team, display_name="Player to keep",
            jersey_number="7", created_by=self.owner,
        )
        duplicate = SportsPlayer.objects.create(
            team=self.team, display_name="Duplicate",
            jersey_number="77", created_by=self.owner,
        )
        SportsPlayerProfile.objects.create(player=duplicate, email="duplicate@example.com")
        game = SportsGame.objects.create(
            team=self.team, opponent_name="Opponent",
            start_at=timezone.now(), created_by=self.owner,
        )
        pa = SoftballPlateAppearance.objects.create(
            game=game, player=duplicate, sequence=1, inning=1,
            result=SoftballPlateAppearance.Result.SINGLE, created_by=self.owner,
        )
        ledger = SoftballStatLedgerEntry.objects.create(
            team=self.team, player=duplicate, games=1, pa=1, ab=1,
            hits=1, created_by=self.owner,
        )
        fee = TeamFee.objects.create(
            team=self.team, title="Team Dues",
            amount_cents=2500, created_by=self.owner,
        )
        assignment = TeamFeeAssignment.objects.create(
            fee=fee, player=duplicate, amount_cents=2500,
            updated_by=self.owner,
        )
        merged = self.client.post(
            f"/api/v1/sports/players/{duplicate.id}/merge/",
            {"target_player": primary.id}, format="json",
        )
        self.assertEqual(merged.status_code, 200)
        self.assertTrue(merged.data["merged"])
        duplicate.refresh_from_db()
        pa.refresh_from_db()
        ledger.refresh_from_db()
        assignment.refresh_from_db()
        self.assertFalse(duplicate.is_active)
        self.assertEqual(duplicate.merged_into_id, primary.id)
        self.assertEqual(pa.player_id, primary.id)
        self.assertEqual(ledger.player_id, primary.id)
        self.assertEqual(assignment.player_id, primary.id)
        self.assertEqual(SportsPlayer.objects.filter(team=self.team, is_active=True).count(), 1)
        self.assertEqual(self.client.post(
            f"/api/v1/sports/players/{duplicate.id}/delete-empty/", {}, format="json",
        ).status_code, 409)

    def test_delete_empty_card_only(self):
        unused = SportsPlayer.objects.create(
            team=self.team, display_name="Mistake", created_by=self.owner,
        )
        response = self.client.post(
            f"/api/v1/sports/players/{unused.id}/delete-empty/", {}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SportsPlayer.objects.filter(pk=unused.id).exists())
