from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from platform_growth.models import GrowthChannelConnection


User = get_user_model()


@override_settings(GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"])
class TestPlatformGrowthStage12B1(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.god = User.objects.create_user(
            username="god@example.com",
            email="god@example.com",
            password="Password123!",
        )
        self.internal_admin = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="Password123!",
            is_platform_admin=True,
        )
        self.sbo = User.objects.create_user(
            username="sbo@example.com",
            email="sbo@example.com",
            password="Password123!",
            role="SBO",
        )
        self.other_sbo = User.objects.create_user(
            username="other-sbo@example.com",
            email="other-sbo@example.com",
            password="Password123!",
            role="SBO",
        )

    def _results(self, response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def _create_connection(self, *, owner, external_account_id="page-owned"):
        return GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Owned Page",
            external_account_id=external_account_id,
            status=GrowthChannelConnection.Status.CONNECTED,
            scopes=["pages_show_list"],
            metadata={"source": "test-oauth"},
            created_by=owner,
        )

    def test_sbo_cannot_post_growth_channels_to_fake_connected_account(self):
        self.client.force_authenticate(user=self.sbo)

        res = self.client.post(
            "/api/v1/platform-growth/growth/channels/",
            {
                "provider": GrowthChannelConnection.Provider.META,
                "account_label": "Fake Page",
                "external_account_id": "fake-page-id",
                "status": GrowthChannelConnection.Status.CONNECTED,
                "scopes": ["pages_show_list", "instagram_basic"],
                "metadata": {"oauth": "fake"},
            },
            format="json",
        )

        self.assertEqual(res.status_code, 403)
        self.assertFalse(GrowthChannelConnection.objects.filter(external_account_id="fake-page-id").exists())

    def test_sbo_cannot_patch_oauth_controlled_connection_fields(self):
        connection = self._create_connection(owner=self.sbo)
        self.client.force_authenticate(user=self.sbo)

        res = self.client.patch(
            f"/api/v1/platform-growth/growth/channels/{connection.id}/",
            {
                "status": GrowthChannelConnection.Status.CONNECTED,
                "external_account_id": "fake-patched-id",
                "scopes": ["pages_show_list", "pages_read_engagement", "instagram_basic"],
                "metadata": {"oauth": "fake-patched"},
            },
            format="json",
        )

        self.assertEqual(res.status_code, 403)
        connection.refresh_from_db()
        self.assertEqual(connection.external_account_id, "page-owned")
        self.assertEqual(connection.scopes, ["pages_show_list"])
        self.assertEqual(connection.metadata, {"source": "test-oauth"})

    def test_sbo_can_list_and_retrieve_their_own_connection(self):
        connection = self._create_connection(owner=self.sbo)
        self.client.force_authenticate(user=self.sbo)

        list_res = self.client.get("/api/v1/platform-growth/growth/channels/")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual([item["id"] for item in self._results(list_res)], [connection.id])

        retrieve_res = self.client.get(f"/api/v1/platform-growth/growth/channels/{connection.id}/")
        self.assertEqual(retrieve_res.status_code, 200)
        self.assertEqual(retrieve_res.data["id"], connection.id)

    def test_another_sbo_cannot_list_retrieve_or_disconnect_someone_elses_connection(self):
        connection = self._create_connection(owner=self.sbo)
        self.client.force_authenticate(user=self.other_sbo)

        list_res = self.client.get("/api/v1/platform-growth/growth/channels/")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(self._results(list_res), [])

        retrieve_res = self.client.get(f"/api/v1/platform-growth/growth/channels/{connection.id}/")
        self.assertEqual(retrieve_res.status_code, 404)

        disconnect_res = self.client.post(f"/api/v1/platform-growth/growth/channels/{connection.id}/disconnect/")
        self.assertEqual(disconnect_res.status_code, 404)

        connection.refresh_from_db()
        self.assertEqual(connection.status, GrowthChannelConnection.Status.CONNECTED)

    def test_sbo_can_disconnect_their_own_connection(self):
        connection = self._create_connection(owner=self.sbo)
        self.client.force_authenticate(user=self.sbo)

        res = self.client.post(f"/api/v1/platform-growth/growth/channels/{connection.id}/disconnect/")

        self.assertEqual(res.status_code, 200)
        connection.refresh_from_db()
        self.assertEqual(connection.status, GrowthChannelConnection.Status.DISCONNECTED)
        self.assertIsNotNone(connection.disconnected_at)

    def test_god_mode_can_manage_growth_channels(self):
        self.client.force_authenticate(user=self.god)

        create_res = self.client.post(
            "/api/v1/platform-growth/growth/channels/",
            {
                "provider": GrowthChannelConnection.Provider.META,
                "account_label": "God Managed Page",
                "external_account_id": "god-page-id",
                "status": GrowthChannelConnection.Status.CONNECTED,
                "scopes": ["pages_show_list"],
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, 201)

        patch_res = self.client.patch(
            f"/api/v1/platform-growth/growth/channels/{create_res.data['id']}/",
            {"account_label": "God Updated Page", "metadata": {"managed_by": "god"}},
            format="json",
        )
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.data["account_label"], "God Updated Page")

    def test_internal_admin_can_manage_growth_channels(self):
        self.client.force_authenticate(user=self.internal_admin)

        create_res = self.client.post(
            "/api/v1/platform-growth/growth/channels/",
            {
                "provider": GrowthChannelConnection.Provider.META,
                "account_label": "Internal Admin Page",
                "external_account_id": "internal-admin-page-id",
                "status": GrowthChannelConnection.Status.CONNECTED,
                "scopes": ["pages_show_list"],
            },
            format="json",
        )

        self.assertEqual(create_res.status_code, 201)
        self.assertEqual(create_res.data["created_by"], self.internal_admin.id)
