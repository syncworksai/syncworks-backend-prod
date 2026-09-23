"""Photo scorebook API protects private source material and official statistics."""
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SportsGame, SportsGameBookPage, SportsTeam


User = get_user_model()


def photo(name="scorebook.jpg"):
    buf = BytesIO()
    Image.new("RGB", (1100, 1400), color=(245, 244, 237)).save(buf, "JPEG", quality=90)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


class PaperGameBookPhotoTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="photo-coach", email="photo-coach@example.com", password="x",
        )
        self.scorer = User.objects.create_user(
            username="photo-scorer", email="photo-scorer@example.com", password="x",
        )
        self.stranger = User.objects.create_user(
            username="photo-stranger", email="photo-stranger@example.com", password="x",
        )
        self.group = SocialGroup.objects.create(
            name="Paper Scorebook Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PUBLIC, created_by=self.coach,
        )
        for member, role in (
            (self.coach, GroupMembership.Role.OWNER),
            (self.scorer, GroupMembership.Role.SCOREKEEPER),
        ):
            GroupMembership.objects.create(
                user=member, group=self.group, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
            )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026", created_by=self.coach,
        )
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Past Opponent",
            start_at=timezone.now() - timedelta(days=14),
            created_by=self.coach,
        )
        self.base = f"/api/v1/sports/games/{self.game.id}/scorebook-pages/"
        self.client.force_authenticate(self.scorer)

    def test_scorekeeper_upload_preserves_original_and_does_not_publish_stats(self):
        uploaded = photo()
        original = uploaded.read()
        uploaded.seek(0)
        response = self.client.post(self.base, {"photo": uploaded}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        page = SportsGameBookPage.objects.get(game=self.game)
        self.assertEqual(bytes(page.image_data), original)
        self.assertEqual(response.data["review_status"], "NEEDS_REVIEW")
        self.assertNotIn("image_data", response.data)
        self.assertEqual(page.uploaded_by, self.scorer)
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, SportsGame.Status.SCHEDULED)
        self.assertEqual(self.game.plate_appearances.count(), 0)
        self.assertEqual(self.game.runs_for, 0)
        listing = self.client.get(self.base)
        self.assertEqual(len(listing.data), 1)
        self.assertNotIn("image_data", listing.data[0])
        image = self.client.get(f"{self.base}{page.id}/image/")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(bytes(image.content), original)
        self.assertEqual(image["Cache-Control"], "private, no-store")
        self.assertEqual(image["Content-Type"], "image/jpeg")

    def test_staff_can_upload_but_only_manager_can_mark_reviewed_or_delete(self):
        page_id = self.client.post(self.base, {"photo": photo()}, format="multipart").data["id"]
        item = f"{self.base}{page_id}/"
        self.assertEqual(
            self.client.patch(item, {"reviewed": True}, format="json").status_code, 403,
        )
        self.assertEqual(self.client.delete(item).status_code, 403)
        self.client.force_authenticate(self.coach)
        approved = self.client.patch(item, {
            "reviewed": True, "notes": "Compared line by line with digital entries.",
        }, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["review_status"], "REVIEWED")
        self.assertIsNotNone(approved.data["reviewed_at"])
        self.assertEqual(self.game.plate_appearances.count(), 0)
        invalid = self.client.patch(item, {"reviewed": "yes"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.delete(item).status_code, 204)
        self.assertFalse(SportsGameBookPage.objects.filter(game=self.game).exists())

    def test_public_team_and_public_gamecast_do_not_expose_originals(self):
        page_id = self.client.post(self.base, {"photo": photo()}, format="multipart").data["id"]
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}{page_id}/image/").status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.base).status_code, (401, 403))
        self.assertIn(self.client.get(f"{self.base}{page_id}/image/").status_code, (401, 403))

    def test_rejects_invalid_image_and_missing_photo(self):
        missing = self.client.post(self.base, {}, format="multipart")
        self.assertEqual(missing.status_code, 400)
        bad = SimpleUploadedFile("fake.jpg", b"not actually a photo", content_type="image/jpeg")
        response = self.client.post(self.base, {"photo": bad}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SportsGameBookPage.objects.count(), 0)

    def test_multiple_pages_are_numbered_and_have_independent_notes(self):
        one = self.client.post(self.base, {
            "photo": photo("first.jpg"), "notes": "Page 1 - visitors",
        }, format="multipart")
        two = self.client.post(self.base, {
            "photo": photo("second.jpg"), "notes": "Page 2 - home",
        }, format="multipart")
        self.assertEqual(one.status_code, 201, one.data)
        self.assertEqual(two.status_code, 201, two.data)
        self.assertEqual([one.data["page_number"], two.data["page_number"]], [1, 2])
        self.assertEqual(two.data["notes"], "Page 2 - home")
