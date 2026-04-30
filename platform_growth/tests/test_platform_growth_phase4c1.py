from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from platform_growth.models import GrowthChannelConnection, GrowthOAuthState, GrowthOAuthToken
from platform_growth.serializers import GrowthOAuthTokenSerializer


User = get_user_model()


@override_settings(
    GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"],
    META_APP_ID="app_123",
    META_APP_SECRET="secret_123",
    META_OAUTH_REDIRECT_URI="http://testserver/api/v1/platform-growth/growth/oauth/meta/callback/",
    META_OAUTH_SCOPES=["public_profile", "pages_show_list", "instagram_basic"],
    META_GRAPH_API_VERSION="v23.0",
    GROWTH_OAUTH_STATE_TTL_SECONDS=900,
)
class TestPlatformGrowthPhase4C1(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.god = User.objects.create_user(username="god@example.com", email="god@example.com", password="Password123!")
        self.client.force_authenticate(user=self.god)

    def test_oauth_start_creates_state(self):
        res = self.client.post("/api/v1/platform-growth/growth/oauth/meta/start/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("authorization_url", res.data)
        self.assertIn("state", res.data)
        self.assertIn("expires_at", res.data)
        self.assertTrue(GrowthOAuthState.objects.filter(state=res.data["state"]).exists())

    def test_callback_rejects_expired_state(self):
        state_obj = GrowthOAuthState.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            state="expired_state",
            redirect_uri="http://testserver/api/v1/platform-growth/growth/oauth/meta/callback/",
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
            created_by=self.god,
        )

        res = self.client.get(
            "/api/v1/platform-growth/growth/oauth/meta/callback/",
            {"code": "abc", "state": state_obj.state},
        )
        self.assertEqual(res.status_code, 400)
        state_obj.refresh_from_db()
        self.assertEqual(state_obj.status, GrowthOAuthState.Status.EXPIRED)

    def test_callback_rejects_reused_state(self):
        state_obj = GrowthOAuthState.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            state="used_state",
            redirect_uri="http://testserver/api/v1/platform-growth/growth/oauth/meta/callback/",
            status=GrowthOAuthState.Status.USED,
            expires_at=timezone.now() + timezone.timedelta(minutes=5),
            created_by=self.god,
        )
        res = self.client.get(
            "/api/v1/platform-growth/growth/oauth/meta/callback/",
            {"code": "abc", "state": state_obj.state},
        )
        self.assertEqual(res.status_code, 400)

    @patch("platform_growth.views.fetch_meta_account_metadata")
    @patch("platform_growth.views.exchange_code_for_token")
    def test_callback_success_with_mocked_meta_response(self, mock_exchange, mock_fetch):
        mock_exchange.return_value = {
            "access_token": "ACCESS123",
            "token_type": "bearer",
            "scope": "public_profile,instagram_basic",
        }
        mock_fetch.return_value = {"id": "meta_user_1", "name": "Meta User"}

        state_obj = GrowthOAuthState.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            state="ok_state",
            redirect_uri="http://testserver/api/v1/platform-growth/growth/oauth/meta/callback/",
            expires_at=timezone.now() + timezone.timedelta(minutes=5),
            created_by=self.god,
        )

        res = self.client.get(
            "/api/v1/platform-growth/growth/oauth/meta/callback/",
            {"code": "abc", "state": state_obj.state},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.get("ok"))

        state_obj.refresh_from_db()
        self.assertEqual(state_obj.status, GrowthOAuthState.Status.USED)

        conn = GrowthChannelConnection.objects.get(external_account_id="meta_user_1")
        self.assertEqual(conn.status, GrowthChannelConnection.Status.CONNECTED)
        token = GrowthOAuthToken.objects.get(connection=conn, is_active=True)
        self.assertEqual(token.access_token, "ACCESS123")

    def test_token_serializer_never_exposes_raw_tokens(self):
        conn = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Meta User",
            external_account_id="meta_user_2",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.god,
        )
        token = GrowthOAuthToken.objects.create(
            connection=conn,
            provider=GrowthChannelConnection.Provider.META,
            token_type="bearer",
            access_token="SENSITIVE_ACCESS",
            refresh_token="SENSITIVE_REFRESH",
            is_active=True,
            created_by=self.god,
        )
        data = GrowthOAuthTokenSerializer(token).data
        self.assertNotIn("access_token", data)
        self.assertNotIn("refresh_token", data)

    def test_disconnect_marks_tokens_inactive(self):
        conn = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Meta User",
            external_account_id="meta_user_3",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.god,
        )
        GrowthOAuthToken.objects.create(
            connection=conn,
            provider=GrowthChannelConnection.Provider.META,
            access_token="ACTIVE",
            is_active=True,
            created_by=self.god,
        )
        res = self.client.post(f"/api/v1/platform-growth/growth/channels/{conn.id}/disconnect/", {}, format="json")
        self.assertEqual(res.status_code, 200)

        conn.refresh_from_db()
        self.assertEqual(conn.status, GrowthChannelConnection.Status.DISCONNECTED)
        self.assertIsNotNone(conn.disconnected_at)
        self.assertFalse(conn.oauth_tokens.filter(is_active=True).exists())
