import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from sync_ai.assist_communications_views import _signature_valid
from user_accounts.models import AuditLog

HUB = "/api/v1/sync-ai/assist/pilot/communications/"
HOOK = "/api/v1/sync-ai/assist/pilot/whatsapp/inbound/"


class SyncAssistCommunicationsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="assist-whatsapp-owner", email="jacoblord7@outlook.com", password="pass12345")
        self.other = User.objects.create_user(username="assist-whatsapp-other", email="unapproved@example.com", password="pass12345")
        self.client = APIClient()

    def test_private_hub_and_no_outbound(self):
        self.assertIn(self.client.get(HUB).status_code, [401, 403])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(HUB).status_code, 403)
        self.client.force_authenticate(self.owner)
        r = self.client.get(HUB)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["whatsapp"]["outbound_enabled"])
        self.assertEqual(r.data["voice"]["status"], "not_connected")

    def test_webhook_disabled_by_default(self):
        with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": "", "SYNC_ASSIST_PILOT_WHATSAPP_TO": ""}):
            r = self.client.post(HOOK, {"MessageSid": "SMabc"}, format="multipart")
        self.assertEqual(r.status_code, 503)

    def test_invalid_signature_is_rejected(self):
        env = {"TWILIO_AUTH_TOKEN": "private-test-token", "SYNC_ASSIST_PILOT_WHATSAPP_TO": "whatsapp:+15555550123"}
        with patch.dict(os.environ, env):
            response = self.client.post(HOOK, {"To": env["SYNC_ASSIST_PILOT_WHATSAPP_TO"], "From": "whatsapp:+15555550000", "MessageSid": "SM123", "Body": "Hello"}, content_type="application/x-www-form-urlencoded", HTTP_X_TWILIO_SIGNATURE="invalid")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.communication_inbound").exists())

    def test_verified_message_is_deduplicated_and_read_only(self):
        env = {"TWILIO_AUTH_TOKEN": "private-test-token", "SYNC_ASSIST_PILOT_WHATSAPP_TO": "whatsapp:+15555550123"}
        params = {"To": env["SYNC_ASSIST_PILOT_WHATSAPP_TO"], "From": "whatsapp:+15555550000", "MessageSid": "SMtest123", "Body": "Need help"}
        import base64
        import hashlib
        import hmac
        from urllib.parse import urlencode
        url = "http://testserver" + HOOK
        payload = url + "".join(k + params[k] for k in sorted(params))
        signature = base64.b64encode(hmac.new(env["TWILIO_AUTH_TOKEN"].encode(), payload.encode(), hashlib.sha1).digest()).decode()
        with patch.dict(os.environ, env):
            for _ in range(2):
                response = self.client.post(HOOK, urlencode(params), content_type="application/x-www-form-urlencoded", HTTP_X_TWILIO_SIGNATURE=signature)
                self.assertEqual(response.status_code, 200)
        entries = AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.communication_inbound")
        self.assertEqual(entries.count(), 1)
        self.client.force_authenticate(self.owner)
        r = self.client.get(HUB)
        self.assertEqual(r.data["messages"][0]["body"], "Need help")
        self.assertFalse(r.data["whatsapp"]["outbound_enabled"])
