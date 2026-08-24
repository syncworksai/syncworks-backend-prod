from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import AuditLog, StripeWebhookEvent
from user_accounts.stripe_webhook_events import claim_stripe_event, mark_stripe_event_failed, mark_stripe_event_processed


class StripeWebhookLedgerHelperTests(APITestCase):
    def event(self, event_id="evt_build23_helper"):
        return {
            "id": event_id,
            "type": "payment_intent.succeeded",
            "livemode": False,
            "api_version": "2024-06-20",
            "data": {"object": {"id": "pi_build23"}},
        }

    def test_duplicate_event_is_claimed_once(self):
        first, first_process = claim_stripe_event(self.event(), endpoint="test")
        self.assertTrue(first_process)
        mark_stripe_event_processed(first)

        duplicate, duplicate_process = claim_stripe_event(self.event(), endpoint="test")
        self.assertFalse(duplicate_process)
        self.assertEqual(duplicate.pk, first.pk)
        self.assertEqual(duplicate.attempts, 2)
        self.assertEqual(duplicate.status, StripeWebhookEvent.Status.PROCESSED)

    def test_failed_event_can_be_retried(self):
        row, should_process = claim_stripe_event(self.event("evt_build23_retry"), endpoint="test")
        self.assertTrue(should_process)
        mark_stripe_event_failed(row, "temporary failure")

        retried, should_retry = claim_stripe_event(self.event("evt_build23_retry"), endpoint="test")
        self.assertTrue(should_retry)
        self.assertEqual(retried.status, StripeWebhookEvent.Status.RECEIVED)
        self.assertEqual(retried.attempts, 2)


@override_settings(ALLOWED_HOSTS=["testserver"])
class SyncAssistantStripeLedgerTests(APITestCase):
    endpoint = "/api/v1/sync-ai/assistant/billing/webhook/"

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="stripe-ledger-user",
            email="stripe-ledger@example.com",
            password="test-password-123",
        )

    def checkout_event(self):
        return {
            "id": "evt_build23_assistant_checkout",
            "type": "checkout.session.completed",
            "livemode": False,
            "api_version": "2024-06-20",
            "data": {
                "object": {
                    "id": "cs_build23",
                    "customer": "cus_build23",
                    "subscription": "sub_build23",
                    "client_reference_id": str(self.user.id),
                    "metadata": {
                        "user_id": str(self.user.id),
                        "jarvis_plan": "PERSONAL",
                        "sync_product": "ASSISTANT",
                    },
                }
            },
        }

    @patch.dict("os.environ", {"STRIPE_JARVIS_WEBHOOK_SECRET": "whsec_test"})
    @patch("sync_ai.jarvis_product_views.stripe.Webhook.construct_event")
    def test_duplicate_assistant_checkout_does_not_duplicate_activation(self, construct_event):
        construct_event.return_value = self.checkout_event()

        first = self.client.post(self.endpoint, data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="sig")
        second = self.client.post(self.endpoint, data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="sig")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["duplicate"])
        self.assertEqual(StripeWebhookEvent.objects.filter(stripe_event_id="evt_build23_assistant_checkout").count(), 1)
        row = StripeWebhookEvent.objects.get(stripe_event_id="evt_build23_assistant_checkout")
        self.assertEqual(row.attempts, 2)
        self.assertEqual(row.status, StripeWebhookEvent.Status.PROCESSED)
        self.assertEqual(
            AuditLog.objects.filter(actor=self.user, action="sync_assistant.subscription.activated").count(),
            1,
        )
