from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

ROOT = "/api/v1/sync-ai/freelance/pilot/"


class FreelancePilotAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.founder = User.objects.create_user(username="freelance-founder", email="jacoblord7@outlook.com", password="x")
        self.other = User.objects.create_user(username="freelance-other", email="other@example.com", password="x")
        self.client = APIClient()

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_private_access_and_nonfounder_denial(self):
        self.assertEqual(self.client.get(ROOT + "access/").status_code, 401)
        self.auth(self.other)
        for path in ["access/", "projects/"]:
            self.assertEqual(self.client.get(ROOT + path).status_code, 403)
        self.auth(self.founder)
        response = self.client.get(ROOT + "access/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["capabilities"]["client_file_storage"])

    def test_founder_project_create_update_owner_scope(self):
        self.auth(self.founder)
        created = self.client.post(ROOT + "projects/", {
            "title": "Test CSV project", "budget": 75, "status": "Contracted",
        }, format="json")
        self.assertEqual(created.status_code, 201)
        project_id = created.data["id"]
        self.assertEqual(len(self.client.get(ROOT + "projects/").data["projects"]), 1)
        updated = self.client.patch(ROOT + f"projects/{project_id}/", {"status": "In progress"}, format="json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["projects"][0]["status"], "In progress")
        self.auth(self.other)
        self.assertEqual(self.client.patch(ROOT + f"projects/{project_id}/", {"status": "Paid"}, format="json").status_code, 403)
        self.assertEqual(self.client.get(ROOT + "projects/").status_code, 403)

    def test_rejects_bad_fields_and_urls(self):
        self.auth(self.founder)
        self.assertEqual(self.client.post(ROOT + "projects/", {"title": "A", "secret": "bad"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(ROOT + "projects/", {"title": "A", "url": "http://unsafe"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(ROOT + "projects/", {"title": "A", "budget": -12}, format="json").status_code, 400)

    def test_csv_processing_does_not_store_contents_and_neutralizes_formulas(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from user_accounts.models import AuditLog
        self.auth(self.founder)
        sample = b"Name,Email\nAlice,ALICE@example.com\nAlice,alice@example.com\n,\n=IMPORTXML(1),x@example.com\n"
        upload = SimpleUploadedFile("test.csv", sample, content_type="text/csv")
        response = self.client.post(ROOT + "process-csv/", {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        report = response.data["report"]
        self.assertEqual(report["duplicate_rows_removed"], 1)
        self.assertEqual(report["empty_rows_removed"], 1)
        import base64
        result = base64.b64decode(response.data["cleaned_csv_base64"]).decode("utf-8")
        self.assertIn("'=IMPORTXML", result)
        serialized = str(list(AuditLog.objects.filter(actor=self.founder).values_list("metadata", flat=True)))
        self.assertNotIn("ALICE@example.com", serialized)
        self.assertNotIn("IMPORTXML", serialized)

    def test_jarvis_requires_explicit_consent_and_does_not_call_provider(self):
        self.auth(self.founder)
        with patch("sync_ai.freelance_pilot_views.create_sync_response") as provider:
            r = self.client.post(ROOT + "jarvis-plan/", {"task": "Plan CSV cleanup"}, format="json")
            self.assertEqual(r.status_code, 400)
            provider.assert_not_called()

    def test_jarvis_sends_only_explicit_short_task(self):
        from unittest.mock import Mock
        self.auth(self.founder)
        with patch("sync_ai.freelance_pilot_views.create_sync_response", return_value=Mock(
            text="Review columns and duplicates.", model="test-model", total_tokens=34,
        )) as provider:
            r = self.client.post(ROOT + "jarvis-plan/", {"task": "Plan cleanup of synthetic CSV", "consent": True}, format="json")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Review columns", r.data["plan"])
            self.assertEqual(provider.call_args.kwargs["message"], "Plan cleanup of synthetic CSV")
