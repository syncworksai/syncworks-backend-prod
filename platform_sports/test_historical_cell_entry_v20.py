"""Final score protection while transcribing actual historical Game Book cells."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from platform_social.models import SocialGroup, GroupMembership
from platform_sports.models import (
    SportsTeam, SportsPlayer, SportsGame, SportsLineupSpot,
    SportsGameBookPhoto, SoftballPlateAppearance, SportsGameInning,
)

User = get_user_model()


class HistoricalCellEntryTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="cell-coach", email="cell-coach@example.test", password="x"
        )
        self.other = User.objects.create_user(
            username="cell-other", email="cell-other@example.test", password="x"
        )
        self.group = SocialGroup.objects.create(
            name="Cell Review Team", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.coach, role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
        )
        self.team = SportsTeam.objects.create(group=self.group, created_by=self.coach)
        self.jake = SportsPlayer.objects.create(
            team=self.team, display_name="Jake", jersey_number="7", created_by=self.coach
        )
        self.outsider = SportsPlayer.objects.create(
            team=self.team, display_name="Unlisted", jersey_number="99", created_by=self.coach
        )
        self.game = SportsGame.objects.create(
            team=self.team, opponent_name="Historical Opponent",
            start_at=timezone.now(), status=SportsGame.Status.FINAL,
            runs_for=14, runs_against=6, created_by=self.coach,
        )
        SportsLineupSpot.objects.create(
            game=self.game, player=self.jake, batting_order=1,
            defensive_position="SS", is_starter=True,
        )
        SportsGameInning.objects.create(game=self.game, inning=1, team_runs=5)
        self.photo = SportsGameBookPhoto.objects.create(
            game=self.game, uploaded_by=self.coach,
            original_name="paper.jpg", content_type="image/jpeg",
            byte_size=5, image_data=b"12345", sha256="a" * 64,
        )
        self.endpoint = f"/api/v1/sports/games/{self.game.pk}/add-historical-play/"

    def payload(self, **overrides):
        value = {
            "source_photo": self.photo.pk, "player": self.jake.pk, "inning": 1,
            "result": "2B", "outs_recorded": 0, "rbi": 2,
            "runs_scored": 2, "notes": "Checked against scorebook photo",
        }
        value.update(overrides)
        return value

    def test_requires_approved_source_and_preserves_official_final(self):
        self.client.force_authenticate(self.coach)
        unreviewed = self.client.post(self.endpoint, self.payload(), format="json")
        self.assertEqual(unreviewed.status_code, 400, unreviewed.data)
        self.photo.review_status = SportsGameBookPhoto.ReviewStatus.REVIEWED
        self.photo.save(update_fields=["review_status"])
        created = self.client.post(self.endpoint, self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.game.refresh_from_db()
        self.assertEqual((self.game.runs_for, self.game.runs_against), (14, 6))
        self.assertEqual(self.game.inning_lines.get(inning=1).team_runs, 5)
        self.assertEqual(SoftballPlateAppearance.objects.get(game=self.game).player_id, self.jake.pk)
        corrected = self.client.patch(
            f"/api/v1/sports/plate-appearances/{created.data['play']['id']}/correct/",
            {"result": "1B", "rbi": 1, "runs_scored": 1},
            format="json",
        )
        self.assertEqual(corrected.status_code, 200, corrected.data)
        self.game.refresh_from_db()
        self.assertEqual((self.game.runs_for, self.game.runs_against), (14, 6))
        self.assertEqual(self.game.inning_lines.get(inning=1).team_runs, 5)

    def test_cannot_assign_another_team_member_without_lineup_or_exceed_runs(self):
        self.client.force_authenticate(self.coach)
        self.photo.review_status = SportsGameBookPhoto.ReviewStatus.REVIEWED
        self.photo.save(update_fields=["review_status"])
        unlisted = self.client.post(self.endpoint, self.payload(player=self.outsider.pk), format="json")
        self.assertEqual(unlisted.status_code, 400, unlisted.data)
        too_many = self.client.post(
            self.endpoint, self.payload(runs_scored=15), format="json"
        )
        self.assertEqual(too_many.status_code, 400, too_many.data)
        outsider = self.client.post(self.endpoint, self.payload(source_photo=444444), format="json")
        self.assertEqual(outsider.status_code, 400, outsider.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(self.endpoint, self.payload(), format="json").status_code, 404)
