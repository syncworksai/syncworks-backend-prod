from datetime import datetime, timezone as utc_timezone
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam,
)
from platform_sports.ops_models import SportsPlayerProfile, SportsPlayerMoment

User = get_user_model()


class EarnedPlayerCardTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="coach-v9@example.com", email="coach-v9@example.com",
            password="test-pass-123",
        )
        self.athlete = User.objects.create_user(
            username="athlete-v9@example.com", email="athlete-v9@example.com",
            password="test-pass-123",
        )
        self.outsider = User.objects.create_user(
            username="outsider-v9@example.com", email="outsider-v9@example.com",
            password="test-pass-123",
        )
        self.group = SocialGroup.objects.create(
            name="Earned Badge Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.owner,
        )
        for user, role in (
            (self.owner, GroupMembership.Role.OWNER),
            (self.athlete, GroupMembership.Role.MEMBER),
        ):
            GroupMembership.objects.create(
                group=self.group, user=user, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.owner,
            )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026", created_by=self.owner,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team, user=self.athlete, display_name="Earned Player",
            jersey_number="7", primary_position="2B", created_by=self.owner,
        )
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Opponents",
            start_at=datetime(2026, 9, 15, 23, 30, tzinfo=utc_timezone.utc),
            timezone="America/Chicago", innings_scheduled=7,
            status=SportsGame.Status.FINAL, created_by=self.owner,
        )
        SportsLineupSpot.objects.create(
            game=self.game, player=self.player, batting_order=1, defensive_position="2B",
        )
        # 10 at-bats, six hits, three doubles = .600 AVG and 3 power points.
        self.plays = []
        for sequence in range(1, 11):
            result = "2B" if sequence <= 3 else "1B" if sequence <= 6 else "OUT"
            self.plays.append(SoftballPlateAppearance.objects.create(
                game=self.game, player=self.player, sequence=sequence,
                result=result, inning=6 if sequence == 3 else min(4, sequence),
                rbi=1 if sequence == 3 else 0,
                runs_scored=0, created_by=self.owner,
            ))
        self.card_url = f"/api/v1/sports/players/{self.player.pk}/badge-card/"
        self.moment_url = f"/api/v1/sports/players/{self.player.pk}/verify-moment/"

    def test_real_stats_unlock_borders_but_not_unverified_speed_or_clutch(self):
        self.client.force_authenticate(self.athlete)
        response = self.client.get(self.card_url)
        self.assertEqual(response.status_code, 200)
        card = response.data
        self.assertEqual(card["season_year"], 2026)
        self.assertEqual(card["season_totals"]["ab"], 10)
        self.assertEqual(card["season_totals"]["h"], 6)
        self.assertEqual(card["season_totals"]["power_points"], 3)
        badges = {row["key"]: row for row in card["badges"]}
        self.assertEqual(badges["POWER"]["tier"], "BRONZE")
        self.assertEqual(badges["CONTACT"]["tier"], "BRONZE")
        self.assertEqual(badges["SPEED"]["tier"], "LOCKED")
        self.assertEqual(badges["CLUTCH"]["tier"], "LOCKED")
        self.assertEqual(card["achieved_count"], 2)
        self.assertEqual(card["month_splits"][0]["label"], "2026-09")
        self.assertEqual(card["year_splits"][0]["year"], 2026)

    def test_speed_is_staff_verified_unique_and_reversible(self):
        self.client.force_authenticate(self.athlete)
        self.assertEqual(self.client.post(
            self.moment_url, {"game": self.game.id, "kind": "EXTRA_BASE"},
            format="json",
        ).status_code, 403)
        self.client.force_authenticate(self.owner)
        created = self.client.post(
            self.moment_url, {"game": self.game.id, "kind": "EXTRA_BASE"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["card"]["badges"][2]["points"], 1)
        self.assertEqual(self.client.post(
            self.moment_url, {"game": self.game.id, "kind": "EXTRA_BASE"},
            format="json",
        ).status_code, 409)
        moment_id = created.data["moment_id"]
        deleted = self.client.delete(
            f"/api/v1/sports/players/{self.player.pk}/moments/{moment_id}/",
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data["card"]["badges"][2]["points"], 0)

    def test_clutch_requires_final_late_rbi_hit_and_manager_attestation(self):
        self.client.force_authenticate(self.owner)
        created = self.client.post(
            self.moment_url, {"game": self.game.id, "kind": "TYING_HIT"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["card"]["badges"][3]["tier"], "BRONZE")
        SportsPlayerMoment.objects.all().delete()
        self.plays[2].inning = 2
        self.plays[2].save(update_fields=["inning"])
        denied = self.client.post(
            self.moment_url, {"game": self.game.id, "kind": "GO_AHEAD_HIT"},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)
        self.assertIn("inning", denied.data["detail"].lower())

    def test_reopening_final_game_recomputes_earned_badges(self):
        self.client.force_authenticate(self.athlete)
        self.game.status = SportsGame.Status.SCHEDULED
        self.game.save(update_fields=["status", "updated_at"])
        response = self.client.get(self.card_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["achieved_count"], 0)

    def test_private_player_card_hidden_from_outsider(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.card_url).status_code, 404)

    def test_photo_survives_as_database_blob_and_card_is_customizable(self):
        out = BytesIO()
        Image.new("RGB", (1200, 900), (23, 68, 112)).save(out, format="JPEG")
        upload = SimpleUploadedFile("avatar.jpg", out.getvalue(), content_type="image/jpeg")
        self.client.force_authenticate(self.athlete)
        response = self.client.post(
            "/api/v1/sports/player-profiles/",
            {
                "player": str(self.player.pk), "profile_photo": upload,
                "card_style": "NEON", "card_nickname": "The Rocket",
                "card_photo_position": "35",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["profile_photo_url"].startswith("data:image/jpeg;base64,"))
        profile = SportsPlayerProfile.objects.get(player=self.player)
        self.assertTrue(profile.card_photo_data)
        self.assertEqual(profile.card_style, "NEON")
        self.assertEqual(profile.card_nickname, "The Rocket")
        self.assertEqual(profile.card_photo_position, 35)
        self.assertFalse(bool(profile.profile_photo))
        reloaded = self.client.get(f"/api/v1/sports/player-profiles/{profile.pk}/")
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.data["profile_photo_url"], response.data["profile_photo_url"])

    def test_rejects_invalid_photo_or_crop(self):
        self.client.force_authenticate(self.athlete)
        invalid = SimpleUploadedFile("wrong.jpg", b"invalid", content_type="image/jpeg")
        response = self.client.post(
            "/api/v1/sports/player-profiles/",
            {"player": str(self.player.pk), "profile_photo": invalid},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        good = self.client.post(
            "/api/v1/sports/player-profiles/",
            {"player": str(self.player.pk), "card_photo_position": "101"},
            format="multipart",
        )
        self.assertEqual(good.status_code, 400)
