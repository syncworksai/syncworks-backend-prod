from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from user_accounts.models import AuditLog

BASE="/api/v1/sync-ai/assist/pilot/"
class ChiefOfStaffLearningTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.pilot=U.objects.create_user(username="jarvislearn",email="jacoblord7@outlook.com",password="password-test")
        self.other=U.objects.create_user(username="jarvisother",email="outsider@example.org",password="password-test")
        self.client=APIClient()

    def test_preferences_are_private_and_never_enable_auto_send(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE+"chief-of-staff/preferences/").status_code,403)
        self.client.force_authenticate(self.pilot)
        initial=self.client.get(BASE+"chief-of-staff/preferences/")
        self.assertEqual(initial.status_code,200)
        self.assertFalse(initial.data["automatic_sending"])
        update=self.client.post(BASE+"chief-of-staff/preferences/",{
            "tone":"direct", "signature":"Thanks", "writing_rules":"Short clear requests.",
            "automated_sending_enabled":True,
        },format="json")
        self.assertEqual(update.status_code,200)
        self.assertEqual(update.data["preferences"]["tone"],"direct")
        self.assertFalse(update.data["preferences"]["automated_sending_enabled"])
        self.assertEqual(self.client.get(BASE+"chief-of-staff/preferences/").data["preferences"]["writing_rules"],"Short clear requests.")

    def test_ai_reply_is_suggestion_only_without_graph_send(self):
        self.client.force_authenticate(self.pilot)
        original={"id":"sample","subject":"Payment followup","from":{"emailAddress":{"address":"recipient@example.org"}},"body":{"content":"Please provide the reconciliation."}}
        with patch("sync_ai.assist_email_intelligence._settings",return_value=object()),patch("sync_ai.assist_email_intelligence._latest",return_value=object()),patch("sync_ai.assist_email_intelligence._graph",return_value=original) as graph,patch("sync_ai.assist_email_intelligence._generate",return_value="Could you share the payment breakdown?") as generate:
            r=self.client.post(BASE+"outlook/suggest/",{"message_id":"sample","purpose":"Ask for details"},format="json")
            self.assertEqual(r.status_code,200)
            self.assertFalse(r.data["sent"])
            self.assertFalse(r.data["saved_in_outlook"])
            self.assertEqual(r.data["recipient"],"recipient@example.org")
            self.assertEqual(graph.call_count,1)
            self.assertEqual(graph.call_args.args[2],"GET")
            self.assertEqual(generate.call_count,1)

    def test_new_message_ai_draft_requires_recipient_subject_and_purpose(self):
        self.client.force_authenticate(self.pilot)
        with patch("sync_ai.assist_email_intelligence._settings",return_value=object()),patch("sync_ai.assist_email_intelligence._latest",return_value=object()),patch("sync_ai.assist_email_intelligence._generate",return_value="Hello, let's talk.") as generate:
            invalid=self.client.post(BASE+"outlook/suggest/",{"recipient":"test@example.net"},format="json")
            self.assertEqual(invalid.status_code,400)
            good=self.client.post(BASE+"outlook/suggest/",{"recipient":"test@example.net","subject":"Intro","purpose":"Invite to demo"},format="json")
            self.assertEqual(good.status_code,200)
            self.assertEqual(good.data["reply_to_id"],"")
            self.assertFalse(good.data["sent"])
            self.assertEqual(generate.call_count,1)
