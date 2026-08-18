from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .connection_store import decrypt_credentials, list_connections, upsert_connection

User = get_user_model()


class CalendarConnectionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="calendar-user", email="calendar@example.com", password="test-password-123")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_connections_require_authentication(self):
        self.client.credentials()
        response = self.client.get("/api/v1/personal-calendar/connections/")
        self.assertEqual(response.status_code, 401)

    def test_multiple_accounts_are_stored_separately_and_credentials_are_encrypted(self):
        upsert_connection(self.user, provider="GOOGLE", external_account_id="g-1", email="one@example.com", display_name="One", credentials={"access_token": "secret-one"}, calendars=[])
        upsert_connection(self.user, provider="GOOGLE", external_account_id="g-2", email="two@example.com", display_name="Two", credentials={"access_token": "secret-two"}, calendars=[])
        rows = list_connections(self.user)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("secret-one", rows[0]["credential_data"])
        self.assertEqual(decrypt_credentials(rows[0]["credential_data"])["access_token"], "secret-one")

    def test_connection_list_never_returns_credentials(self):
        upsert_connection(self.user, provider="GOOGLE", external_account_id="g-1", email="one@example.com", display_name="One", credentials={"access_token": "secret-one"}, calendars=[])
        response = self.client.get("/api/v1/personal-calendar/connections/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("credential_data", response.data["connections"][0])

    def test_user_can_change_cadence_and_disconnect(self):
        row = upsert_connection(self.user, provider="GOOGLE", external_account_id="g-1", email="one@example.com", display_name="One", credentials={"access_token": "secret-one"}, calendars=[])
        response = self.client.patch(f"/api/v1/personal-calendar/connections/{row['id']}/", {"sync_cadence": "FIVE_MIN"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sync_cadence"], "FIVE_MIN")
        response = self.client.delete(f"/api/v1/personal-calendar/connections/{row['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list_connections(self.user), [])

    @patch.dict("os.environ", {"GOOGLE_CALENDAR_CLIENT_ID": "test-client"})
    def test_google_oauth_start_returns_authorization_url(self):
        response = self.client.post("/api/v1/personal-calendar/connections/oauth/start/", {"provider": "GOOGLE"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("accounts.google.com", response.data["authorization_url"])
