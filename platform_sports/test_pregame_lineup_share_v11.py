from datetime import datetime, timezone as utc_tz

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam


User = get_user_model()


class PregameLineupWatchLinkTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="v11-coach@example.com", email="v11-coach@example.com", password="test-password",
        )
        self.group = SocialGroup.objects.create(
            name="V11 Pregame Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.owner, status=GroupMembership.Status.ACTIVE,
            role=GroupMembership.Role.OWNER, invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026", created_by=self.owner,
        )
        self.players = [
            SportsPlayer.objects.create(
                team=self.team, display_name=f"Player {n}",
                jersey_number=str(n), created_by=self.owner,
            ) for n in range(1, 4)
        ]
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Test Visitors",
            start_at=datetime(2026, 9, 26, 23, 30, tzinfo=utc_tz.utc),
            venue_name="Test Field", timezone="America/Chicago",
            innings_scheduled=7, status=SportsGame.Status.SCHEDULED,
            created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)
        self.base = f"/api/v1/sports/games/{self.game.id}/"

    def test_one_player_per_defensive_position_and_extra_hitters(self):
        dup = [
            {"player": self.players[0].id, "batting_order": 1, "defensive_position": "SS"},
            {"player": self.players[1].id, "batting_order": 2, "defensive_position": "SS"},
        ]
        self.assertEqual(self.client.post(self.base+"set-lineup/", {"spots": dup}, format="json").status_code, 400)
        valid = [
            {"player": self.players[0].id, "batting_order": 1, "defensive_position": "SS"},
            {"player": self.players[1].id, "batting_order": 2, "defensive_position": "MM"},
            {"player": self.players[2].id, "batting_order": 3, "defensive_position": "EH1"},
        ]
        result = self.client.post(self.base+"set-lineup/", {"spots": valid}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["lineup_spots"][1]["defensive_position"], "MM")
        self.assertEqual(result.data["lineup_spots"][2]["defensive_position"], "EH1")

    def test_watch_url_exists_and_is_publicly_fetchable_before_first_pitch(self):
        settings = self.client.post(self.base+"gamecast/", {"enabled": True}, format="json")
        self.assertEqual(settings.status_code, 200)
        token = settings.data["token"]
        self.assertTrue(settings.data["enabled"])
        landing = self.client.get("/api/v1/sports/games/gamecast-public/", {"token": token})
        self.assertEqual(landing.status_code, 200, landing.data)
        self.assertEqual(landing.data["game"]["status"], "SCHEDULED")
        self.assertEqual(landing.data["game"]["venue_name"], "Test Field")
        self.assertIsNotNone(landing.data["game"]["start_at"])
        followup = self.client.get(self.base+"gamecast/")
        self.assertEqual(followup.data["token"], token)
        self.assertEqual(followup.data["enabled"], True)

    def test_start_after_valid_lineup_preserves_shared_gamecast_link_and_locks_replacement(self):
        spots=[
            {"player": self.players[0].id, "batting_order": 1, "defensive_position": "SS"},
            {"player": self.players[1].id, "batting_order": 2, "defensive_position": "MM"},
            {"player": self.players[2].id, "batting_order": 3, "defensive_position": "EH1"},
        ]
        self.assertEqual(self.client.post(self.base+"set-lineup/", {"spots":spots}, format="json").status_code, 200)
        token=self.client.post(self.base+"gamecast/", {"enabled": True}, format="json").data["token"]
        started=self.client.post(self.base+"start/", {}, format="json")
        self.assertEqual(started.status_code, 200, started.data)
        response=self.client.get("/api/v1/sports/games/gamecast-public/", {"token":token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["game"]["status"], "LIVE")
        replacement=self.client.post(self.base+"set-lineup/", {"spots":spots}, format="json")
        self.assertEqual(replacement.status_code, 409)
        self.assertIn("substitutions", replacement.data["detail"])

    def test_shared_gamecast_link_is_accessible_to_guests_only_when_enabled(self):
        url = "/api/v1/sports/games/gamecast-public/"
        token = str(self.game.gamecast_token)
        self.client.force_authenticate(user=None)
        hidden = self.client.get(url, {"token": token})
        self.assertEqual(hidden.status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(
            self.base+"gamecast/", {"enabled": True}, format="json"
        ).status_code, 200)
        # Linked user details contain a private account email in the
        # internal roster serializer, but the guest watch link must not.
        self.players[0].user = self.owner
        self.players[0].save(update_fields=("user", "updated_at"))
        SportsLineupSpot.objects.create(
            game=self.game, player=self.players[0], batting_order=1,
            defensive_position="SS",
        )
        self.client.force_authenticate(user=None)
        visible = self.client.get(url, {"token": token})
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(visible.data["game"]["status"], "SCHEDULED")
        self.assertNotIn("email", visible.data["game"])
        self.assertNotIn("user_detail", visible.data["game"]["current_batter"])
        self.assertNotIn(self.owner.email, str(visible.data))
        self.client.force_authenticate(self.owner)
        self.client.post(self.base+"gamecast/", {"enabled": False}, format="json")
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(url, {"token": token}).status_code, 404)
