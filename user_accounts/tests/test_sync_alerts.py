from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import CommunicationPreference, Notification
from user_accounts.services.sync_alerts import AlertCandidate, sync_alerts_for_user


class SyncAlertEngineTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sync-alert-user",
            email="alerts@example.com",
            password="test-password-123",
        )
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def candidate(self, *, severity="HIGH", body="Traffic added 18 minutes."):
        return AlertCandidate(
            source="TRAVEL",
            code="TRAVEL_CHANGE",
            severity=severity,
            title="Travel plan changed",
            body=body,
            deep_link="/customer/calendar",
            dedupe_key="SYNC:TRAVEL:TRAVEL_CHANGE:event-1",
            payload={"event_id": 1},
        )

    @patch("user_accounts.services.sync_alerts._email_alert", return_value=True)
    @patch("user_accounts.services.sync_alerts.collect_personal_alert_candidates")
    def test_high_priority_alert_is_deduped_and_emailed_once(self, collect, email):
        collect.return_value = [self.candidate()]
        first = sync_alerts_for_user(self.user)
        second = sync_alerts_for_user(self.user)
        self.assertEqual(Notification.objects.filter(recipient=self.user, data__sync_alert=True).count(), 1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["emailed"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["emailed"], 0)
        self.assertEqual(email.call_count, 1)

    @patch("user_accounts.services.sync_alerts._email_alert", return_value=True)
    @patch("user_accounts.services.sync_alerts._quiet_hours_active", return_value=True)
    @patch("user_accounts.services.sync_alerts.collect_personal_alert_candidates")
    def test_quiet_hours_suppress_high_email_but_keep_in_app_alert(self, collect, quiet, email):
        collect.return_value = [self.candidate(severity="HIGH")]
        result = sync_alerts_for_user(self.user)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["emailed"], 0)
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)
        email.assert_not_called()

    @patch("user_accounts.services.sync_alerts._email_alert", return_value=True)
    @patch("user_accounts.services.sync_alerts.collect_personal_alert_candidates")
    def test_low_priority_is_in_app_and_held_for_digest(self, collect, email):
        collect.return_value = [self.candidate(severity="LOW", body="Workout still planned." )]
        result = sync_alerts_for_user(self.user)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["emailed"], 0)
        email.assert_not_called()

    @patch("user_accounts.services.sync_alerts.collect_personal_alert_candidates")
    def test_changed_alert_reopens_existing_notification(self, collect):
        collect.return_value = [self.candidate(body="Traffic added 12 minutes.")]
        sync_alerts_for_user(self.user, send_email=False)
        notification = Notification.objects.get(recipient=self.user)
        notification.mark_read()
        collect.return_value = [self.candidate(body="Traffic added 28 minutes.")]
        sync_alerts_for_user(self.user, send_email=False)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)
        self.assertIn("28", notification.body)

    def test_alert_api_is_user_scoped_and_exposes_summary(self):
        other = get_user_model().objects.create_user(
            username="other-alert-user",
            email="other-alerts@example.com",
            password="test-password-123",
        )
        Notification.objects.create(
            recipient=self.user,
            type=Notification.TYPE_REMINDER,
            title="My alert",
            body="Mine",
            data={"sync_alert": True, "source": "FINANCE", "severity": "HIGH", "dedupe_key": "mine"},
        )
        Notification.objects.create(
            recipient=other,
            type=Notification.TYPE_REMINDER,
            title="Other alert",
            body="Other",
            data={"sync_alert": True, "source": "TRAVEL", "severity": "CRITICAL", "dedupe_key": "other"},
        )
        response = self.client.get("/api/v1/me/notifications/?sync_alerts=true")
        self.assertEqual(response.status_code, 200)
        rows = response.data.get("results", response.data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "My alert")
        summary = self.client.get("/api/v1/me/notifications/summary/")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["total"], 1)
        self.assertEqual(summary.data["by_source"]["FINANCE"], 1)

    def test_existing_personal_preferences_are_used(self):
        preference = CommunicationPreference.objects.create(
            user=self.user,
            business=None,
            scope=CommunicationPreference.Scope.PERSONAL,
            email_notifications_enabled=False,
            push_notifications_enabled=False,
        )
        self.assertFalse(preference.email_notifications_enabled)
        response = self.client.get("/api/v1/communication-preferences/current/?scope=PERSONAL")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["email_notifications_enabled"])
