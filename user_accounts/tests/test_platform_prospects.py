from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from user_accounts.models import (
    Business, PlatformBusinessProspect, PlatformProspectActivity, User,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="notifications@syncworksapp.com",
    FRONTEND_URL="https://syncworksapp.com",
)
class PlatformProspectTests(TestCase):
    def setUp(self):
        self.founder = User.objects.create_user(
            username="prospect-founder",
            email="jacoblord7@outlook.com",
            password="SecureTestPass123!",
        )
        self.other = User.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="SecureTestPass123!",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.founder)

    def test_restrict_non_founder_even_if_staff(self):
        self.other.is_staff = True
        self.other.is_superuser = True
        self.other.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_authenticate(self.other)
        result = self.client.get("/api/v1/platform/prospects/")
        self.assertEqual(result.status_code, 403)

    def test_create_invite_history_and_metrics(self):
        created = self.client.post(
            "/api/v1/platform/prospects/",
            {
                "company_name": "Test Electric",
                "contact_name": "Chris",
                "email": "CHRIS@EXAMPLE.COM",
                "interests": ["DISPATCH", "ROUTING"],
                "next_action": "Send setup invitation",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        prospect_id = created.data["id"]
        sent = self.client.post(f"/api/v1/platform/prospects/{prospect_id}/send-invite/")
        self.assertEqual(sent.status_code, 200, sent.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/register?business=1&email=chris%40example.com", mail.outbox[0].body)
        self.assertEqual(
            PlatformProspectActivity.objects.filter(
                prospect_id=prospect_id, kind="INVITATION",
            ).count(), 1,
        )
        self.assertEqual(
            self.client.post(f"/api/v1/platform/prospects/{prospect_id}/send-invite/").status_code,
            429,
        )
        metrics = self.client.get("/api/v1/platform/prospects/metrics/")
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.data["invited"], 1)
        self.assertEqual(metrics.data["registered"], 0)

    def test_signup_matching_uses_verified_account_email(self):
        new_owner = User.objects.create_user(
            username="business-owner",
            email="electric@example.com",
            password="SecureTestPass123!",
        )
        record = PlatformBusinessProspect.objects.create(
            company_name="Test Electric", email="electric@example.com",
            created_by=self.founder,
        )
        Business.objects.create(
            name="Test Electric", owner=new_owner,
        )
        rows = self.client.get("/api/v1/platform/prospects/")
        self.assertEqual(rows.status_code, 200)
        record.refresh_from_db()
        self.assertIsNotNone(record.linked_business_id)
        self.assertEqual(record.status, "REGISTERED")
        self.assertIsNotNone(record.signed_up_at)

    def test_ambiguous_businesses_do_not_claim_wrong_conversion(self):
        owner = User.objects.create_user(
            username="multiple-owner", email="multi@example.com",
            password="SecureTestPass123!",
        )
        Business.objects.create(name="First Services", owner=owner)
        Business.objects.create(name="Second Services", owner=owner)
        record = PlatformBusinessProspect.objects.create(
            company_name="Unknown Services",
            email="multi@example.com", created_by=self.founder,
        )
        self.client.get("/api/v1/platform/prospects/")
        record.refresh_from_db()
        self.assertIsNone(record.linked_business_id)

    def test_outreach_history_cannot_forge_sent_invitation(self):
        created = self.client.post(
            "/api/v1/platform/prospects/",
            {"company_name": "Another Service"},
            format="json",
        )
        pid = created.data["id"]
        res = self.client.post(
            f"/api/v1/platform/prospects/{pid}/log-activity/",
            {"kind": "INVITATION", "body": "I sent this"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            PlatformProspectActivity.objects.filter(prospect_id=pid, kind="INVITATION").count(),
            0,
        )
