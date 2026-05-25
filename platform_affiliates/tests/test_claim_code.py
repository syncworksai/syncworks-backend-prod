from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from platform_affiliates.models import AffiliatePartner, ReferralAttribution
from user_accounts.models import Business


User = get_user_model()


class AffiliateClaimCodeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner1",
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="One",
        )

        self.other_user = User.objects.create_user(
            username="other1",
            email="other@example.com",
            password="testpass123",
            first_name="Other",
            last_name="One",
        )

        self.business = Business.objects.create(
            owner=self.owner,
            name="Test Plumbing LLC",
            business_email="owner@example.com",
            owner_name="Owner One",
        )

        self.affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="affiliate@example.com",
            code="SWSC01",
            status="ACTIVE",
        )

    def token_client(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    def test_business_owner_can_claim_active_affiliate_code(self):
        client = self.token_client(self.owner)

        response = client.post(
            "/api/v1/platform-affiliates/claim-code/",
            {
                "business_id": self.business.id,
                "code": "swsc01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.assertTrue(
            ReferralAttribution.objects.filter(
                business=self.business,
                affiliate=self.affiliate,
                referral_code="SWSC01",
            ).exists()
        )

    def test_random_user_cannot_claim_code_for_business_they_do_not_own(self):
        client = self.token_client(self.other_user)

        response = client.post(
            "/api/v1/platform-affiliates/claim-code/",
            {
                "business_id": self.business.id,
                "code": "SWSC01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReferralAttribution.objects.exists())

    def test_business_cannot_claim_two_affiliate_codes(self):
        client = self.token_client(self.owner)

        first = client.post(
            "/api/v1/platform-affiliates/claim-code/",
            {
                "business_id": self.business.id,
                "code": "SWSC01",
            },
            format="json",
        )

        self.assertEqual(first.status_code, 201)

        second_affiliate = AffiliatePartner.objects.create(
            name="Affiliate Two",
            email="affiliate2@example.com",
            code="SWSC02",
            status="ACTIVE",
        )

        second = client.post(
            "/api/v1/platform-affiliates/claim-code/",
            {
                "business_id": self.business.id,
                "code": second_affiliate.code,
            },
            format="json",
        )

        self.assertEqual(second.status_code, 400)
        self.assertEqual(ReferralAttribution.objects.count(), 1)

    def test_inactive_affiliate_code_cannot_be_claimed(self):
        self.affiliate.status = "SUSPENDED"
        self.affiliate.save(update_fields=["status", "updated_at"])

        client = self.token_client(self.owner)

        response = client.post(
            "/api/v1/platform-affiliates/claim-code/",
            {
                "business_id": self.business.id,
                "code": "SWSC01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReferralAttribution.objects.exists())