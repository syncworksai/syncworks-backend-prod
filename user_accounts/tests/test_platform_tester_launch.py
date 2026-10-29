from django.test import TestCase, override_settings
from django.core import mail
from user_accounts.viewsets.platform_business_prospects import PILOT_REQUIRED_CHECKS
from rest_framework.test import APIClient

from user_accounts.models import Business, PlatformBusinessProspect
from user_accounts.models.user import User
from user_accounts.services.god_mode import FOUNDER_GOD_MODE_EMAIL


class TesterLaunchTests(TestCase):
    def setUp(self):
        self.founder = User.objects.create_user(username="test-founder", email=FOUNDER_GOD_MODE_EMAIL, password="UseSecureTestPwd123!")
        self.other_user = User.objects.create_user(username="tester-intruder", email="intruder@example.com", password="UseSecureTestPwd123!")
        self.prospect = PlatformBusinessProspect.objects.create(company_name="Pilot Test Services", email="pilot-owner@example.com", created_by=self.founder)
        self.client = APIClient()

    def test_only_god_mode_can_view_or_mutate_pilot_state(self):
        self.client.force_authenticate(user=self.other_user)
        url = f"/api/v1/platform/prospects/{self.prospect.pk}/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.patch(url, {"pilot_status": "TESTING"}, format="json").status_code, 403)

    def test_stage_progress_and_checklist_validation(self):
        self.client.force_authenticate(user=self.founder)
        url = f"/api/v1/platform/prospects/{self.prospect.pk}/"
        response = self.client.patch(url, {"pilot_status": "ONBOARDING", "pilot_checks": {"signup": True}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.pilot_status, "ONBOARDING")
        self.assertEqual(self.prospect.pilot_checks["signup"], True)
        invalid = self.client.patch(url, {"pilot_checks": {"signup": "yes"}}, format="json")
        self.assertEqual(invalid.status_code, 400)
        premature = self.client.patch(url, {"pilot_status": "COMPLETE"}, format="json")
        self.assertEqual(premature.status_code, 400)
        self.assertEqual(self.client.get("/api/v1/platform/prospects/metrics/").status_code, 200)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_completion_needs_linked_business_and_manual_checks(self):
        self.client.force_authenticate(user=self.founder)
        business = Business.objects.create(name="Pilot Test Services", owner=self.other_user)
        self.prospect.linked_business = business
        self.prospect.save(update_fields=["linked_business"])
        checks = {key: True for key in PILOT_REQUIRED_CHECKS}
        url = f"/api/v1/platform/prospects/{self.prospect.pk}/"
        complete = self.client.patch(url, {"pilot_status": "COMPLETE", "pilot_checks": checks}, format="json")
        self.assertEqual(complete.status_code, 200, complete.data)
        self.assertEqual(complete.data["pilot_status"], "COMPLETE")
        self.assertFalse(complete.data["completion_notified"])
        notify = self.client.post(f"/api/v1/platform/prospects/{self.prospect.pk}/send-completion/", {}, format="json")
        self.assertEqual(notify.status_code, 200, notify.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("no new subscription", mail.outbox[0].body.lower()) if "no new subscription" in mail.outbox[0].body.lower() else self.assertIn("No new subscription", mail.outbox[0].body)
        again = self.client.post(f"/api/v1/platform/prospects/{self.prospect.pk}/send-completion/", {}, format="json")
        self.assertEqual(again.status_code, 200, again.data)
        self.assertTrue(again.data["already_sent"])
        self.assertEqual(len(mail.outbox), 1)


    def test_notification_rejects_unapproved_and_no_marketing(self):
        self.client.force_authenticate(user=self.founder)
        self.assertEqual(self.client.post(
            f"/api/v1/platform/prospects/{self.prospect.pk}/send-completion/",
            {}, format="json").status_code, 409)
        self.assertEqual(self.client.patch(
            f"/api/v1/platform/prospects/{self.prospect.pk}/",
            {"pilot_checks": {"customer_import": "yes"}}, format="json").status_code, 400)
