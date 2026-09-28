from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient


class CalendarRuntimeTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_runtime_rejects_missing_identity(self):
        response = self.client.post("/api/v1/personal-calendar/runtime/run/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    @patch("personal_calendar.runtime_views.refresh_operational_sync_alerts")
    @patch("personal_calendar.runtime_views.refresh_sync_alerts")
    @patch("personal_calendar.runtime_views.refresh_due_trip_monitors")
    @patch("personal_calendar.runtime_views.verify_calendar_runtime_token")
    @patch("personal_calendar.runtime_views.sync_due_connections")
    def test_runtime_runs_due_syncs_for_valid_github_identity(
        self, sync_due, verify_token, refresh_trip, refresh_alerts, refresh_operational
    ):
        verify_token.return_value = {"run_id": "12345"}
        sync_due.return_value = {"due": 3, "synced": 2, "failed": 1}
        refresh_trip.return_value = {"checked": 0}
        refresh_alerts.return_value = {"users": 6, "failed": 0}
        refresh_operational.return_value = {"social": {}, "operations": {}}

        response = self.client.post(
            "/api/v1/personal-calendar/runtime/run/",
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer oidc-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.data["due"], 3)
        self.assertEqual(response.data["synced"], 2)
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["identity"], "github:12345")
        verify_token.assert_called_once_with("oidc-token")
        sync_due.assert_called_once()
        refresh_trip.assert_called_once()
        self.assertEqual(refresh_alerts.call_args.kwargs["user_limit"], 6)
        self.assertGreaterEqual(refresh_alerts.call_args.kwargs["user_offset"], 0)
        refresh_operational.assert_called_once()

    @patch("personal_calendar.runtime_views.verify_calendar_runtime_token")
    def test_runtime_rejects_invalid_oidc(self, verify_token):
        from personal_calendar.github_oidc import CalendarOIDCError

        verify_token.side_effect = CalendarOIDCError("bad token")
        response = self.client.post(
            "/api/v1/personal-calendar/runtime/run/",
            {},
            format="json",
            HTTP_AUTHORIZATION="Bearer bad-token",
        )
        self.assertEqual(response.status_code, 403)
