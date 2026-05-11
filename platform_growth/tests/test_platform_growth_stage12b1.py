from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from platform_growth.models import GrowthChannelConnection, GrowthOAuthState, GrowthOAuthToken


User = get_user_model()


class FakeMetaResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("meta error")

    def json(self):
        return self.payload


@override_settings(
    GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"],
    META_APP_ID="meta-app-id",
    META_APP_SECRET="meta-app-secret",
    META_GRAPH_API_VERSION="v20.0",
    META_OAUTH_REDIRECT_URI="https://api.example.com/api/v1/platform-growth/growth/oauth/meta/callback/",
    META_OAUTH_SCOPES="pages_show_list,pages_read_engagement,instagram_basic",
)
class TestPlatformGrowthStage12B2(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.sbo = User.objects.create_user(
            username="sbo12b2@example.com",
            email="sbo12b2@example.com",
            password="Password123!",
            role="SBO",
        )
        self.other_sbo = User.objects.create_user(
            username="other12b2@example.com",
            email="other12b2@example.com",
            password="Password123!",
            role="SBO",
        )
        self.god = User.objects.create_user(
            username="god@example.com",
            email="god@example.com",
            password="Password123!",
        )

    def _create_state(self, *, user=None, status=GrowthOAuthState.Status.PENDING, expires_at=None):
        return GrowthOAuthState.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            state=f"state-{GrowthOAuthState.objects.count() + 1}",
            redirect_uri="https://api.example.com/api/v1/platform-growth/growth/oauth/meta/callback/",
            status=status,
            expires_at=expires_at or timezone.now() + timedelta(minutes=15),
            metadata={"scopes": ["pages_show_list", "pages_read_engagement", "instagram_basic"]},
            created_by=user or self.sbo,
        )

    def test_start_returns_authorization_url_and_creates_owned_state(self):
        self.client.force_authenticate(user=self.sbo)

        res = self.client.post("/api/v1/platform-growth/growth/oauth/meta/start/", {}, format="json")

        self.assertEqual(res.status_code, 200)
        self.assertIn("authorization_url", res.data)
        self.assertIn("state", res.data)

        state = GrowthOAuthState.objects.get(state=res.data["state"])
        self.assertEqual(state.created_by, self.sbo)
        self.assertEqual(state.provider, GrowthChannelConnection.Provider.META)
        self.assertEqual(state.status, GrowthOAuthState.Status.PENDING)

        parsed = urlparse(res.data["authorization_url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "www.facebook.com")
        self.assertIn("/v20.0/dialog/oauth", parsed.path)
        self.assertEqual(query["client_id"], ["meta-app-id"])
        self.assertEqual(query["redirect_uri"], ["https://api.example.com/api/v1/platform-growth/growth/oauth/meta/callback/"])
        self.assertEqual(query["state"], [state.state])
        self.assertEqual(query["scope"], ["pages_show_list,pages_read_engagement,instagram_basic"])

    @override_settings(META_APP_ID="", META_OAUTH_REDIRECT_URI="")
    def test_start_missing_config_returns_clean_400(self):
        self.client.force_authenticate(user=self.sbo)

        res = self.client.post("/api/v1/platform-growth/growth/oauth/meta/start/", {}, format="json")

        self.assertEqual(res.status_code, 400)
        self.assertIn("META_APP_ID", res.data["detail"])
        self.assertIn("META_OAUTH_REDIRECT_URI", res.data["detail"])
        self.assertEqual(GrowthOAuthState.objects.count(), 0)

    def test_callback_rejects_missing_state_or_code(self):
        self.client.force_authenticate(user=self.sbo)

        missing_state = self.client.get("/api/v1/platform-growth/growth/oauth/meta/callback/?code=abc")
        self.assertEqual(missing_state.status_code, 400)

        missing_code = self.client.get("/api/v1/platform-growth/growth/oauth/meta/callback/?state=abc")
        self.assertEqual(missing_code.status_code, 400)

    @patch("platform_growth.services.meta_oauth.requests.get")
    def test_callback_rejects_invalid_expired_and_used_state(self, mock_get):
        self.client.force_authenticate(user=self.sbo)

        invalid = self.client.get("/api/v1/platform-growth/growth/oauth/meta/callback/?code=abc&state=missing")
        self.assertEqual(invalid.status_code, 400)

        expired_state = self._create_state(expires_at=timezone.now() - timedelta(minutes=1))
        expired = self.client.get(
            f"/api/v1/platform-growth/growth/oauth/meta/callback/?code=abc&state={expired_state.state}"
        )
        self.assertEqual(expired.status_code, 400)
        expired_state.refresh_from_db()
        self.assertEqual(expired_state.status, GrowthOAuthState.Status.EXPIRED)

        used_state = self._create_state(status=GrowthOAuthState.Status.USED)
        used = self.client.get(
            f"/api/v1/platform-growth/growth/oauth/meta/callback/?code=abc&state={used_state.state}"
        )
        self.assertEqual(used.status_code, 400)

        other_owner_state = self._create_state(user=self.other_sbo)
        forbidden = self.client.get(
            f"/api/v1/platform-growth/growth/oauth/meta/callback/?code=abc&state={other_owner_state.state}"
        )
        self.assertEqual(forbidden.status_code, 403)
        mock_get.assert_not_called()

    @patch("platform_growth.services.meta_oauth.requests.post")
    @patch("platform_growth.services.meta_oauth.requests.get")
    def test_valid_callback_creates_connection_and_token_without_exposing_raw_token(self, mock_get, mock_post):
        state = self._create_state(user=self.sbo)
        mock_get.side_effect = [
            FakeMetaResponse({"access_token": "user-token-secret", "token_type": "bearer", "expires_in": 3600}),
            FakeMetaResponse({"id": "meta-user-1", "name": "Meta User"}),
            FakeMetaResponse(
                {
                    "data": [
                        {
                            "id": "page-123",
                            "name": "Connected Page",
                            "access_token": "page-token-secret",
                            "instagram_business_account": {"id": "ig-456", "username": "connected_ig"},
                        }
                    ]
                }
            ),
        ]
        self.client.force_authenticate(user=self.sbo)

        res = self.client.get(
            f"/api/v1/platform-growth/growth/oauth/meta/callback/?code=valid-code&state={state.state}"
        )

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["ok"])
        self.assertTrue(res.data["no_external_post"])
        self.assertNotIn("access_token", json.dumps(res.data, default=str))
        self.assertNotIn("page-token-secret", json.dumps(res.data, default=str))
        self.assertNotIn("user-token-secret", json.dumps(res.data, default=str))

        connection = GrowthChannelConnection.objects.get(external_account_id="page-123")
        self.assertEqual(connection.created_by, self.sbo)
        self.assertEqual(connection.account_label, "Connected Page")
        self.assertEqual(connection.status, GrowthChannelConnection.Status.CONNECTED)
        self.assertEqual(connection.scopes, ["pages_show_list", "pages_read_engagement", "instagram_basic"])
        self.assertEqual(connection.metadata["account_kind"], "facebook_page")
        self.assertNotIn("access_token", json.dumps(connection.metadata, default=str))

        token = GrowthOAuthToken.objects.get(connection=connection)
        self.assertEqual(token.created_by, self.sbo)
        self.assertEqual(token.access_token, "page-token-secret")
        self.assertEqual(token.token_type, "bearer")
        self.assertTrue(token.is_active)
        self.assertIsNotNone(token.expires_at)

        state.refresh_from_db()
        self.assertEqual(state.status, GrowthOAuthState.Status.USED)
        self.assertIsNotNone(state.used_at)
        self.assertEqual(state.metadata["connection_id"], connection.id)
        self.assertEqual(state.metadata["token_id"], token.id)

        mock_post.assert_not_called()
        requested_urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertTrue(any(url.endswith("/oauth/access_token") for url in requested_urls))
        self.assertTrue(any(url.endswith("/me") for url in requested_urls))
        self.assertTrue(any(url.endswith("/me/accounts") for url in requested_urls))
        self.assertFalse(any("/feed" in url or "/photos" in url or "/media" in url for url in requested_urls))

    @patch("platform_growth.services.meta_oauth.requests.get")
    def test_valid_callback_reuses_existing_owned_connection_and_deactivates_old_token(self, mock_get):
        state = self._create_state(user=self.sbo)
        connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            external_account_id="page-123",
            account_label="Old Page Name",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.sbo,
        )
        old_token = GrowthOAuthToken.objects.create(
            connection=connection,
            provider=GrowthChannelConnection.Provider.META,
            access_token="old-secret",
            is_active=True,
            created_by=self.sbo,
        )
        mock_get.side_effect = [
            FakeMetaResponse({"access_token": "new-user-token", "token_type": "bearer"}),
            FakeMetaResponse({"id": "meta-user-1", "name": "Meta User"}),
            FakeMetaResponse({"data": [{"id": "page-123", "name": "New Page Name", "access_token": "new-page-token"}]}),
        ]
        self.client.force_authenticate(user=self.sbo)

        res = self.client.get(
            f"/api/v1/platform-growth/growth/oauth/meta/callback/?code=valid-code&state={state.state}"
        )

        self.assertEqual(res.status_code, 200)
        connection.refresh_from_db()
        old_token.refresh_from_db()
        self.assertEqual(connection.account_label, "New Page Name")
        self.assertFalse(old_token.is_active)
        self.assertEqual(connection.oauth_tokens.filter(is_active=True).count(), 1)
