from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsPlayer, SportsTeam
from platform_sports.ops_models import SportsPlayerAward, SportsPlayerProfile


User = get_user_model()


class TeamEngagementTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(username="coach18", email="coach18@example.com", password="x")
        self.player_user = User.objects.create_user(username="player18", email="player18@example.com", password="x")
        self.other = User.objects.create_user(username="other18", email="other18@example.com", password="x")
        self.group = SocialGroup.objects.create(
            name="Engagement Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.coach, role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.player_user, role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(group=self.group, sport="SOFTBALL", season_name="Fall 2026", created_by=self.coach)
        self.player = SportsPlayer.objects.create(
            team=self.team, user=self.player_user, display_name="Player One", jersey_number="7", created_by=self.coach,
        )
        self.profile = SportsPlayerProfile.objects.create(
            player=self.player, email=self.player_user.email, date_of_birth="1990-04-15",
        )
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        for index, hour in enumerate((18, 19), start=1):
            local = datetime.combine(monday + timedelta(days=1), datetime.min.time()).replace(hour=hour, tzinfo=dt_timezone.utc)
            game = SportsGame.objects.create(
                team=self.team, opponent_name=f"Opponent {index}", start_at=local,
                status=SportsGame.Status.SCHEDULED, created_by=self.coach,
            )
            from platform_sports.views import sync_game_social_event
            sync_game_social_event(game)
        self.week_start = monday.isoformat()

    def test_player_can_answer_both_games_and_manager_sees_week(self):
        self.client.force_authenticate(self.player_user)
        route = f"/api/v1/sports/teams/{self.team.id}/weekly-availability/?week_start={self.week_start}"
        before = self.client.get(route)
        self.assertEqual(before.status_code, 200, before.data)
        self.assertEqual(len(before.data["games"]), 2)
        self.assertTrue(all(row["my_response"]["response"] == "PENDING" for row in before.data["games"]))
        responses = {str(row["game"]["id"]): "YES" for row in before.data["games"]}
        saved = self.client.post(
            f"/api/v1/sports/teams/{self.team.id}/respond-weekly-availability/",
            {"week_start": self.week_start, "responses": responses},
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["updated"], 2)
        self.assertTrue(all(row["my_response"]["response"] == "YES" for row in saved.data["games"]))

        self.client.force_authenticate(self.coach)
        manager = self.client.get(route)
        self.assertEqual(manager.status_code, 200)
        roster = next(row for row in manager.data["roster"] if row["player"]["id"] == self.player.id)
        self.assertTrue(roster["all_yes"])
        self.assertEqual(roster["pending"], 0)

    def test_player_updates_private_dob_and_coach_can_award(self):
        self.client.force_authenticate(self.player_user)
        response = self.client.patch(
            f"/api/v1/sports/player-profiles/{self.profile.id}/",
            {"date_of_birth": "1991-05-20", "show_age_to_team": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["date_of_birth"], "1991-05-20")
        self.assertIsInstance(response.data["age"], int)

        forbidden = self.client.post(
            "/api/v1/sports/player-awards/",
            {"team": self.team.id, "player": self.player.id, "kind": "HUSTLE", "title": "Hustle Award"},
            format="json",
        )
        self.assertEqual(forbidden.status_code, 400)

        self.client.force_authenticate(self.coach)
        award = self.client.post(
            "/api/v1/sports/player-awards/",
            {
                "team": self.team.id, "player": self.player.id, "kind": "PLAYER_OF_WEEK",
                "title": "Player of the Week", "season_name": "Fall 2026",
                "week_of": self.week_start, "note": "Great effort and teammate support.",
            },
            format="json",
        )
        self.assertEqual(award.status_code, 201, award.data)
        self.assertEqual(SportsPlayerAward.objects.filter(player=self.player).count(), 1)

        self.client.force_authenticate(self.other)
        hidden = self.client.get(f"/api/v1/sports/player-awards/?player={self.player.id}")
        self.assertEqual(hidden.status_code, 200)
        rows = hidden.data.get("results", []) if isinstance(hidden.data, dict) else hidden.data
        self.assertEqual(len(rows), 0)
