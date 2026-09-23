from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import (
    SoftballPlateAppearance, SportsGame, SportsGameBookPhoto, SportsLineupSpot,
    SportsPlayer, SportsTeam,
)
from platform_sports.views import softball_player_stats


User = get_user_model()


class HistoricalScorebookImportTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="historical-coach", email="historic@example.test", password="pw"
        )
        self.stranger = User.objects.create_user(
            username="historic-outsider", email="other@example.test", password="pw"
        )
        self.group = SocialGroup.objects.create(
            name="Historical Bed Springs",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.coach, role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(group=self.group, created_by=self.coach)
        self.jake = SportsPlayer.objects.create(
            team=self.team, display_name="Jake", jersey_number="7",
            created_by=self.coach,
        )
        self.ethan = SportsPlayer.objects.create(
            team=self.team, display_name="Ethan", jersey_number="6",
            created_by=self.coach,
        )
        self.freedom = SportsGame.objects.create(
            team=self.team, opponent_name="Freedom Church",
            start_at=timezone.now(), created_by=self.coach,
        )
        self.frazer = SportsGame.objects.create(
            team=self.team, opponent_name="Frazer Church",
            start_at=timezone.now(), created_by=self.coach,
        )
        self.client.force_authenticate(self.coach)

    def book(self, game, lineup, plays, runs_for=1, runs_against=0):
        return self.client.post(
            f"/api/v1/sports/games/{game.pk}/import-historical-book/",
            {
                "lineup": lineup,
                "plays": plays,
                "runs_for": runs_for,
                "runs_against": runs_against,
            },
            format="json",
        )

    def test_lineup_changes_assign_hits_by_player_id_and_reimport_does_not_duplicate(self):
        # The same players can swap order across games without swapping their stats.
        first_lineup = [
            {"player": self.jake.pk, "batting_order": 1},
            {"player": self.ethan.pk, "batting_order": 2},
        ]
        first_plays = [
            {"player": self.jake.pk, "inning": 1, "result": "1B", "runs_scored": 1},
            {"player": self.ethan.pk, "inning": 1, "result": "OUT", "outs_recorded": 1},
        ]
        first = self.book(self.freedom, first_lineup, first_plays, runs_for=1, runs_against=2)
        self.assertEqual(first.status_code, 200, first.data)
        second_lineup = [
            {"player": self.ethan.pk, "batting_order": 1},
            {"player": self.jake.pk, "batting_order": 2},
        ]
        second_plays = [
            {"player": self.ethan.pk, "inning": 1, "result": "2B", "runs_scored": 1},
            {"player": self.jake.pk, "inning": 1, "result": "OUT", "outs_recorded": 1},
        ]
        second = self.book(self.frazer, second_lineup, second_plays, runs_for=1, runs_against=0)
        self.assertEqual(second.status_code, 200, second.data)
        duplicate = self.book(self.frazer, second_lineup, second_plays, runs_for=1, runs_against=0)
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertEqual(SoftballPlateAppearance.objects.filter(game=self.frazer).count(), 2)
        self.assertEqual(SportsLineupSpot.objects.get(game=self.freedom, player=self.jake).batting_order, 1)
        self.assertEqual(SportsLineupSpot.objects.get(game=self.frazer, player=self.jake).batting_order, 2)
        stats = {row["player"]["id"]: row for row in softball_player_stats(self.team)}
        self.assertEqual(stats[self.jake.pk]["h"], 1)
        self.assertEqual(stats[self.ethan.pk]["h"], 1)
        self.assertEqual(stats[self.ethan.pk]["double"], 1)

    def test_unknown_player_and_score_mismatch_cannot_replace_a_valid_book(self):
        valid = self.book(
            self.freedom,
            [{"player": self.jake.pk, "batting_order": 1}],
            [{"player": self.jake.pk, "result": "1B", "runs_scored": 1}],
        )
        self.assertEqual(valid.status_code, 200, valid.data)
        bad_player = self.book(
            self.freedom, [{"player": 999999, "batting_order": 1}],
            [{"player": 999999, "result": "HR", "runs_scored": 1}],
        )
        self.assertEqual(bad_player.status_code, 400)
        incomplete = self.book(
            self.freedom, [{"player": self.ethan.pk, "batting_order": 1}],
            [{"player": self.ethan.pk, "result": "1B", "runs_scored": 0}],
        )
        self.assertEqual(incomplete.status_code, 400)
        self.assertEqual(SoftballPlateAppearance.objects.get(game=self.freedom).player_id, self.jake.pk)

    def test_photo_upload_is_deduplicated_and_private(self):
        route = "/api/v1/sports/game-book-photos/"
        photo = lambda: SimpleUploadedFile(
            "scorebook.jpg", b"scorebook-sample-bytes", content_type="image/jpeg"
        )
        first = self.client.post(
            route, {"game": str(self.freedom.pk), "image": photo()}, format="multipart"
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(
            route, {"game": str(self.freedom.pk), "image": photo()}, format="multipart"
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(SportsGameBookPhoto.objects.filter(game=self.freedom).count(), 1)
        image = self.client.get(f"{route}{first.data['id']}/image/")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, b"scorebook-sample-bytes")
        self.client.force_authenticate(self.stranger)
        denied = self.client.get(f"{route}{first.data['id']}/image/")
        self.assertEqual(denied.status_code, 404)
        denied_upload = self.client.post(
            route, {"game": str(self.freedom.pk), "image": photo()}, format="multipart"
        )
        self.assertEqual(denied_upload.status_code, 403)
