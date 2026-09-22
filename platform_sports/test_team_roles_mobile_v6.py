from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam


User = get_user_model()


class TeamRolesMobileSportsV6Tests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner-v6@example.com",
            email="owner-v6@example.com",
            password="test-pass-123",
        )
        self.scorer = User.objects.create_user(
            username="scorer-v6@example.com",
            email="scorer-v6@example.com",
            password="test-pass-123",
        )
        self.group = SocialGroup.objects.create(
            name="Bed Springs Test",
            kind=SocialGroup.Kind.TEAM,
            category=SocialGroup.Category.SPORTS,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.owner,
        )
        self.owner_membership = GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.scorer_membership = GroupMembership.objects.create(
            group=self.group,
            user=self.scorer,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            created_by=self.owner,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team,
            display_name="Player One",
            jersey_number="7",
            created_by=self.owner,
        )
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Opponent",
            start_at=timezone.now() + timedelta(hours=1),
            created_by=self.owner,
        )
        SportsLineupSpot.objects.create(
            game=self.game,
            player=self.player,
            batting_order=1,
            defensive_position="2B",
        )

    def test_owner_can_assign_scorekeeper_role(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/social/memberships/{self.scorer_membership.id}/set-role/",
            {"role": "SCOREKEEPER"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.scorer_membership.refresh_from_db()
        self.assertEqual(self.scorer_membership.role, GroupMembership.Role.SCOREKEEPER)

    def test_scorekeeper_can_run_game_book_but_not_delete_it(self):
        self.scorer_membership.role = GroupMembership.Role.SCOREKEEPER
        self.scorer_membership.save(update_fields=("role", "updated_at"))

        self.client.force_authenticate(self.scorer)
        detail = self.client.get(f"/api/v1/sports/games/{self.game.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.data["can_score"])
        self.assertFalse(detail.data["can_manage"])

        start = self.client.post(f"/api/v1/sports/games/{self.game.id}/start/", {}, format="json")
        self.assertEqual(start.status_code, 200)

        play = self.client.post(
            f"/api/v1/sports/games/{self.game.id}/play/",
            {
                "result": "1B",
                "outs_recorded": 0,
                "rbi": 0,
                "runs_scored": 0,
            },
            format="json",
        )
        self.assertEqual(play.status_code, 201)

        delete_book = self.client.post(
            f"/api/v1/sports/games/{self.game.id}/delete-book/",
            {},
            format="json",
        )
        self.assertEqual(delete_book.status_code, 403)

    def test_manager_cannot_escalate_roles_or_change_director(self):
        manager = User.objects.create_user(
            username="manager-v6@example.com",
            email="manager-v6@example.com",
            password="test-pass-123",
        )
        manager_membership = GroupMembership.objects.create(
            group=self.group,
            user=manager,
            role=GroupMembership.Role.MANAGER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.client.force_authenticate(manager)
        promote_self = self.client.post(
            f"/api/v1/social/memberships/{manager_membership.id}/set-role/",
            {"role": "DIRECTOR"},
            format="json",
        )
        self.assertEqual(promote_self.status_code, 403)

        promote_other = self.client.post(
            f"/api/v1/social/memberships/{self.scorer_membership.id}/set-role/",
            {"role": "DIRECTOR"},
            format="json",
        )
        self.assertEqual(promote_other.status_code, 403)

        assign_scorer = self.client.post(
            f"/api/v1/social/memberships/{self.scorer_membership.id}/set-role/",
            {"role": "SCOREKEEPER"},
            format="json",
        )
        self.assertEqual(assign_scorer.status_code, 200)

        self.client.force_authenticate(self.owner)
        assign_director = self.client.post(
            f"/api/v1/social/memberships/{self.scorer_membership.id}/set-role/",
            {"role": "DIRECTOR"},
            format="json",
        )
        self.assertEqual(assign_director.status_code, 200)

        self.client.force_authenticate(manager)
        demote_director = self.client.post(
            f"/api/v1/social/memberships/{self.scorer_membership.id}/set-role/",
            {"role": "MEMBER"},
            format="json",
        )
        self.assertEqual(demote_director.status_code, 403)
