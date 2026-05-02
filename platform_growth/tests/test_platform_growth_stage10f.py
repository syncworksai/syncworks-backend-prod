from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from platform_growth.models import (
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
)

User = get_user_model()


@override_settings(GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"])
class TestPlatformGrowthStage10F(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.god = User.objects.create_user(
            username="god@example.com",
            email="god@example.com",
            password="Password123!",
        )
        self.normal = User.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password="Password123!",
        )
        self.draft = GrowthContentDraft.objects.create(
            title="Draft 1",
            body="Body",
            source="AUTOMATION",
            status=GrowthContentDraft.Status.DRAFT,
            created_by=self.god,
        )

    def test_god_mode_can_queue_draft(self):
        self.client.force_authenticate(user=self.god)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/drafts/{self.draft.id}/queue/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], GrowthContentQueueItem.Status.QUEUED)

    def test_non_god_mode_blocked_from_queueing_draft(self):
        self.client.force_authenticate(user=self.normal)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/drafts/{self.draft.id}/queue/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 403)

    def test_queue_without_channel_uses_safe_mode_connection(self):
        self.client.force_authenticate(user=self.god)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/drafts/{self.draft.id}/queue/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 201)

        queue_item = GrowthContentQueueItem.objects.get(id=res.data["id"])
        self.assertEqual(queue_item.channel_connection.provider, GrowthChannelConnection.Provider.META)
        self.assertEqual(queue_item.channel_connection.external_account_id, "safe-mode")
        self.assertEqual(queue_item.channel_connection.account_label, "Manual / Safe Mode")
        self.assertTrue(queue_item.metadata.get("safe_mode"))
        self.assertTrue(queue_item.metadata.get("no_external_post"))

    def test_queue_with_missing_channel_returns_400(self):
        self.client.force_authenticate(user=self.god)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/drafts/{self.draft.id}/queue/",
            {"channel_connection": 999999},
            format="json",
        )

        self.assertEqual(res.status_code, 400)

    def test_simulate_post_marks_item_posted(self):
        self.client.force_authenticate(user=self.god)

        connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Manual / Safe Mode",
            external_account_id="safe-mode",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.god,
        )

        queue_item = GrowthContentQueueItem.objects.create(
            draft=self.draft,
            channel_connection=connection,
            status=GrowthContentQueueItem.Status.QUEUED,
            created_by=self.god,
            metadata={"safe_mode": True, "no_external_post": True},
        )

        res = self.client.post(
            f"/api/v1/platform-growth/growth/queue/{queue_item.id}/simulate-post/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 200)

        queue_item.refresh_from_db()
        self.assertEqual(queue_item.status, GrowthContentQueueItem.Status.POSTED)
        self.assertIsNotNone(queue_item.posted_at)
        self.assertTrue(queue_item.metadata.get("simulated_post"))
        self.assertTrue(queue_item.metadata.get("no_external_post"))

    def test_non_god_mode_blocked_from_simulate_post(self):
        connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Manual / Safe Mode",
            external_account_id="safe-mode",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.god,
        )

        queue_item = GrowthContentQueueItem.objects.create(
            draft=self.draft,
            channel_connection=connection,
            status=GrowthContentQueueItem.Status.QUEUED,
            created_by=self.god,
            metadata={"safe_mode": True, "no_external_post": True},
        )

        self.client.force_authenticate(user=self.normal)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/queue/{queue_item.id}/simulate-post/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 403)

    def test_queue_and_simulate_post_do_not_create_oauth_tokens(self):
        self.client.force_authenticate(user=self.god)

        res = self.client.post(
            f"/api/v1/platform-growth/growth/drafts/{self.draft.id}/queue/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 201)

        queue_item = GrowthContentQueueItem.objects.get(id=res.data["id"])

        res = self.client.post(
            f"/api/v1/platform-growth/growth/queue/{queue_item.id}/simulate-post/",
            {},
            format="json",
        )

        self.assertEqual(res.status_code, 200)

        queue_item.refresh_from_db()
        self.assertTrue(queue_item.metadata.get("safe_mode"))
        self.assertTrue(queue_item.metadata.get("no_external_post"))
        self.assertTrue(queue_item.metadata.get("simulated_post"))