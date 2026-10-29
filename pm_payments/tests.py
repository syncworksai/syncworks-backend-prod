from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from unittest.mock import patch
from user_accounts.viewsets.pm_rent import PMRentChargeViewSet

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

    def test_old_rent_checkout_cannot_charge_platform_without_payout(self):
        request = APIRequestFactory().post("/api/v1/pm/rent/charges/1/checkout/", {}, format="json")
        force_authenticate(request, user=self.owner)
        with patch.object(PMRentChargeViewSet, "get_object", return_value=object()):
            response = PMRentChargeViewSet.as_view({"post": "checkout"})(request, pk=1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "PM_ONLINE_RENT_NOT_RELEASED")

    def test_owner_can_save_five_step_baseline_without_enabling_collection(self):
        self.client.force_authenticate(user=self.owner)
        url = "/api/v1/payment-migration/plan/"
        initial = self.client.get(url, **self.header)
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertEqual(initial.data["completed_count"], 0)
        self.assertFalse(initial.data["online_collection_enabled"])
        first = self.client.patch(url, {"workspace_reviewed": True}, format="json", **self.header)
        self.assertEqual(first.status_code, 200, first.data)
        second = self.client.patch(url, {
            "current_processor": "Current bank merchant",
            "current_monthly_fees": "58.75",
            "current_monthly_transactions": 40,
            "average_payout_days": "2.5",
            "monthly_reconciliation_hours": "6.0",
            "costs_reviewed": True,
        }, format="json", **self.header)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["completed_count"], 2)
        self.assertEqual(second.data["current_monthly_fees"], "58.75")
        self.assertFalse(second.data["bank_ready"])
        denied = self.client.patch(url, {"request_switch": True}, format="json", **self.header)
        self.assertEqual(denied.status_code, 400)
        reread = self.client.get(url, **self.header)
        self.assertEqual(reread.data["completed_count"], 2)
        self.assertFalse(reread.data["switch_requested"])

    def test_no_cross_tenant_access_or_fake_processor_verification(self):
        self.client.force_authenticate(user=self.other)
        url = "/api/v1/payment-migration/plan/"
        self.assertEqual(self.client.get(url, **self.header).status_code, 403)
        self.assertEqual(self.client.patch(url, {"workspace_reviewed": True}, format="json", **self.header).status_code, 403)
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.patch(url, {"bank_ready": True}, format="json", **self.header).status_code, 400)
        self.assertEqual(self.client.patch(url, {"founder_test_reviewed": True}, format="json", **self.header).status_code, 400)
        bad_evidence = self.client.patch(url, {"test_evidence": {"bank_deposit_verified": "yes"}}, format="json", **self.header)
        self.assertEqual(bad_evidence.status_code, 400)
        self.assertEqual(self.client.post("/api/v1/payment-migration/review-test/",
                {"notes": "approve"}, format="json", **self.header).status_code, 403)

    def test_request_test_review_requires_connected_payouts_and_evidence(self):
        self.client.force_authenticate(user=self.owner)
        url = "/api/v1/payment-migration/plan/"
        self.client.patch(url, {"workspace_reviewed": True}, format="json", **self.header)
        self.client.patch(url, {
            "current_processor": "Existing Processor", "current_monthly_fees": "20.00",
            "costs_reviewed": True,
        }, format="json", **self.header)
        missing = self.client.patch(url, {"request_test_review": True}, format="json", **self.header)
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(self.client.get(url, **self.header).data["online_collection_enabled"])
