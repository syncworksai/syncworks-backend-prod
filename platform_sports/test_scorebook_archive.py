"""Scorebook photos are private; review and import are atomic and idempotent."""
from datetime import datetime, timezone
from io import BytesIO

from django.contrib.auth import get_user_model
from PIL import Image
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from .models import (
    SoftballPlateAppearance, SportsGame, SportsPlayer, SportsScorebookPage,
    SportsScorebookReview, SportsTeam, SportsSubstitution,
)


class ScorebookArchiveTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.coach = User.objects.create_user(
            username="scan-coach@example.com", email="scan-coach@example.com", password="secret",
        )
        self.viewer = User.objects.create_user(
            username="scan-viewer@example.com", email="scan-viewer@example.com", password="secret",
        )
        self.stranger = User.objects.create_user(
            username="scan-other@example.com", email="scan-other@example.com", password="secret",
        )
        self.group = SocialGroup.objects.create(
            name="Private Scan Squad", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        for user, role in (
            (self.coach, GroupMembership.Role.OWNER),
            (self.viewer, GroupMembership.Role.MEMBER),
        ):
            GroupMembership.objects.create(
                group=self.group, user=user, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
            )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL, created_by=self.coach,
        )
        self.players = [
            SportsPlayer.objects.create(
                team=self.team, display_name=f"Scan Player {idx}", jersey_number=str(idx),
                created_by=self.coach,
            ) for idx in range(1, 4)
        ]
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Scan Opposition",
            start_at=datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc),
            created_by=self.coach,
        )
        self.base = f"/api/v1/sports/games/{self.game.id}/"
        self.client.force_authenticate(self.coach)

    def _photo(self):
        output = BytesIO()
        Image.new("RGB", (400, 500), color="white").save(output, format="JPEG")
        output.seek(0)
        output.name = "original-scorebook.jpg"
        return output

    def _upload(self, side="TEAM"):
        return self.client.post(
            self.base + "scorebook-pages/", {"side": side, "photo": self._photo()},
            format="multipart",
        )

    def _review(self):
        return {
            "innings": [
                {"inning": 1, "team_runs": 2, "opponent_runs": 1},
                {"inning": 2, "team_runs": 0, "opponent_runs": 0},
            ],
            "lineup": [
                {"batting_order": 1, "player": self.players[0].id},
                {"batting_order": 2, "player": self.players[1].id},
            ],
            "substitutions": [{
                "after_sequence": 2, "batting_order": 1,
                "incoming_player": self.players[2].id,
            }],
            "plays": [
                {"batting_order": 1, "player": self.players[0].id,
                 "inning": 1, "result": "1B", "runs_scored": 0},
                {"batting_order": 2, "player": self.players[1].id,
                 "inning": 1, "result": "HR", "runs_scored": 2, "rbi": 2},
                {"batting_order": 1, "player": self.players[2].id,
                 "inning": 2, "result": "1B", "runs_scored": 0},
                {"batting_order": 2, "player": self.players[1].id,
                 "inning": 2, "result": "OUT", "outs_recorded": 1},
            ],
        }

    def test_photo_private_idempotent_and_rotate(self):
        first = self._upload()
        self.assertEqual(first.status_code, 201, first.data)
        duplicate = self._upload(side="OPPONENT")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(SportsScorebookPage.objects.filter(game=self.game).count(), 1)
        page_id = first.data["id"]
        image_url = self.base + f"scorebook-pages/{page_id}/image/"
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        patch = self.client.patch(
            self.base + f"scorebook-pages/{page_id}/",
            {"rotation": 90, "side": "TEAM"}, format="json",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.data["rotation"], 90)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(image_url).status_code, 200)
        self.assertEqual(self._upload().status_code, 403)
        self.client.force_authenticate(self.stranger)
        self.assertIn(self.client.get(image_url).status_code, (403, 404))
        self.assertIn(self.client.get(self.base + "scorebook-pages/").status_code, (403, 404))

    def test_approve_score_only_does_not_create_any_player_statistics(self):
        self.assertEqual(self._upload().status_code, 201)
        draft = self.client.put(
            self.base + "scorebook-review/",
            {"payload": {"innings": self._review()["innings"]}}, format="json",
        )
        self.assertEqual(draft.status_code, 200)
        response = self.client.post(self.base + "scorebook-review/confirm/", {
            "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            "approve_plays": False,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, SportsGame.Status.FINAL)
        self.assertEqual((self.game.runs_for, self.game.runs_against), (2, 1))
        self.assertFalse(SoftballPlateAppearance.objects.filter(game=self.game).exists())
        again = self.client.post(self.base + "scorebook-review/confirm/", {
            "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            "approve_plays": False,
        }, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.game.inning_lines.count(), 2)

    def test_player_identity_survives_substitution_and_repeat_confirm(self):
        self.assertEqual(self._upload().status_code, 201)
        draft = self.client.put(
            self.base + "scorebook-review/", {"payload": self._review()}, format="json",
        )
        response = self.client.post(self.base + "scorebook-review/confirm/", {
            "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            "approve_plays": True,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], SportsScorebookReview.Status.FULLY_VERIFIED)
        appearances = list(SoftballPlateAppearance.objects.filter(game=self.game).order_by("sequence"))
        self.assertEqual([p.player_id for p in appearances], [
            self.players[0].id, self.players[1].id, self.players[2].id, self.players[1].id,
        ])
        self.assertEqual(self.game.substitutions.count(), 1)
        substitution = SportsSubstitution.objects.get(game=self.game)
        self.assertEqual(substitution.outgoing_player_id, self.players[0].id)
        self.assertEqual(substitution.incoming_player_id, self.players[2].id)
        self.assertEqual(
            self.client.post(self.base + "scorebook-review/confirm/", {
                "confirmed": True, "expected_sha256": draft.data["current_sha256"],
                "approve_plays": True,
            }, format="json").status_code, 200,
        )
        self.assertEqual(SoftballPlateAppearance.objects.filter(game=self.game).count(), 4)

    def test_wrong_player_for_slot_refused_without_changing_official_game(self):
        self.assertEqual(self._upload().status_code, 201)
        payload = self._review()
        payload["plays"][2]["player"] = self.players[0].id
        draft = self.client.put(
            self.base + "scorebook-review/", {"payload": payload}, format="json",
        )
        response = self.client.post(self.base + "scorebook-review/confirm/", {
            "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            "approve_plays": True,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("substitution", response.data["detail"])
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, SportsGame.Status.SCHEDULED)
        self.assertFalse(self.game.plate_appearances.exists())

    def test_unscanned_and_viewer_approval_rejected(self):
        payload = {"innings": self._review()["innings"]}
        draft = self.client.put(
            self.base + "scorebook-review/", {"payload": payload}, format="json",
        )
        self.assertEqual(
            self.client.post(self.base + "scorebook-review/confirm/", {
                "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            }, format="json").status_code, 400,
        )
        self.assertEqual(self._upload().status_code, 201)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(
            self.client.post(self.base + "scorebook-review/confirm/", {
                "confirmed": True, "expected_sha256": draft.data["current_sha256"],
            }, format="json").status_code, 403,
        )
