from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from user_accounts.models import AuditLog
from .assist_outlook_views import DRAFT_EVENT, SENT_EVENT, _settings

BASE="/api/v1/sync-ai/assist/pilot/outlook/"

class OutlookPilotTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.pilot=U.objects.create_user(username="outlookpilot",email="jacoblord7@outlook.com",password="examplepassword")
        self.other=U.objects.create_user(username="outlookother",email="external-user@example.org",password="examplepassword")
        self.client=APIClient()

    def test_nonpilot_denied_every_sensitive_api(self):
        self.client.force_authenticate(self.other)
        for path in ["status/","inbox/"]:
            self.assertEqual(self.client.get(BASE+path).status_code,403)
        for path in ["connect/","draft/","send/","disconnect/"]:
            self.assertEqual(self.client.post(BASE+path,{},format="json").status_code,403)

    def test_oauth_unconfigured_does_not_access_mail_or_send(self):
        self.client.force_authenticate(self.pilot)
        with patch("sync_ai.assist_outlook_views._settings",return_value=None):
            status=self.client.get(BASE+"status/")
            self.assertEqual(status.status_code,200)
            self.assertFalse(status.data["connected"])
            self.assertTrue(status.data["approval_required"])
            self.assertFalse(status.data["outbound_automatic"])
            self.assertEqual(self.client.post(BASE+"connect/",{},format="json").status_code,503)
            self.assertEqual(self.client.get(BASE+"inbox/").status_code,409)
            self.assertEqual(self.client.post(BASE+"draft/",{"body":"hello"},format="json").status_code,409)
            self.assertEqual(self.client.post(BASE+"send/",{"draft_id":"abc","confirmation":"SEND"},format="json").status_code,409)

    def test_send_requires_explicit_approval_and_owner_created_draft(self):
        self.client.force_authenticate(self.pilot)
        with patch("sync_ai.assist_outlook_views._settings",return_value=object()),patch("sync_ai.assist_outlook_views._latest",return_value=object()),patch("sync_ai.assist_outlook_views._graph") as graph:
            self.assertEqual(self.client.post(BASE+"send/",{"draft_id":"abc"},format="json").status_code,400)
            self.assertEqual(self.client.post(BASE+"send/",{"draft_id":"abc","confirmation":"SEND"},format="json").status_code,404)
            self.assertEqual(graph.call_count,0)

    def test_disconnection_invalidates_local_credentials(self):
        self.client.force_authenticate(self.pilot)
        self.assertEqual(self.client.post(BASE+"disconnect/",{},format="json").status_code,200)
        self.assertEqual(self.client.get(BASE+"status/").status_code,200)
        self.assertFalse(self.client.get(BASE+"status/").data["connected"])
