from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from user_accounts.models.business import Business
from pm_payments.models import PMCollectionSetup

User = get_user_model()


class PMCollectionSetupTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="pm_col_owner", email="owner+pm@example.com", password="SomeStrongPassword123!")
        self.other = User.objects.create_user(username="pm_col_other", email="other+pm@example.com", password="SomeStrongPassword123!")
        self.business = Business.objects.create(name="Property Management Test", owner=self.owner)
        self.client = APIClient()
        self.url = "/api/v1/pm-collection/setup/"
        self.header = {"HTTP_X_BUSINESS_ID": str(self.business.id)}

    def test_unconfigured_is_not_enabled_and_contains_no_bank_details(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.url, **self.header)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["method"], "UNCONFIGURED")
        self.assertFalse(response.data["online_rent_collection_enabled"])
        self.assertEqual(response.data["fee_policy"]["amount_cents"], 100)
        self.assertNotIn("routing_number", response.data)
        self.assertNotIn("account_number", response.data)

    def test_external_and_offline_modes_do_not_enable_live_collection(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(self.url, {
            "method": "EXTERNAL",
            "external_provider_name": "ExistingProcessor",
            "external_provider_url": "https://example.com/payments"
        }, format="json", **self.header)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["online_rent_collection_enabled"])
        self.assertEqual(response.data["external_provider_name"], "ExistingProcessor")
        manual = self.client.patch(self.url, {"method": "MANUAL"}, format="json", **self.header)
        self.assertEqual(manual.status_code, 200, manual.data)
        self.assertEqual(manual.data["external_provider_url"], "")

    def test_unsafe_external_url_and_unknown_fields_rejected(self):
        self.client.force_authenticate(user=self.owner)
        for url in ("http://example.com/pay", "https://127.0.0.1/secret", "https://name:password@example.com/", "https://localhost/test"):
            response = self.client.patch(self.url, {
                "method": "EXTERNAL", "external_provider_name": "Payment", "external_provider_url": url
            }, format="json", **self.header)
            self.assertEqual(response.status_code, 400, (url, response.data))
        forbidden = self.client.patch(self.url, {"online_rent_collection_enabled": True}, format="json", **self.header)
        self.assertEqual(forbidden.status_code, 400)
        self.assertFalse(PMCollectionSetup.objects.get(business_id=self.business.id).method == "STRIPE_CONNECT")

    def test_cross_business_account_is_denied(self):
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(self.url, **self.header).status_code, 403)
        self.assertEqual(self.client.patch(self.url, {"method": "STRIPE_CONNECT"}, format="json", **self.header).status_code, 403)

    def test_stripe_setup_is_not_payment_authorization(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(self.url, {"method": "STRIPE_CONNECT", "trust_account_reviewed": True}, format="json", **self.header)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["trust_account_reviewed"])
        self.assertFalse(response.data["online_rent_collection_enabled"])
        self.assertTrue(any("not yet enabled" in r for r in response.data["readiness_reasons"]))
