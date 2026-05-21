from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from platform_affiliates.choices import AttributionSource, RevenueSource
from platform_affiliates.models import (
    AffiliateAgreementAcceptance,
    AffiliateAuditLog,
    AffiliateCommissionLedger,
    AffiliatePartner,
    ReferralAttribution,
)
from platform_affiliates.services.attribution_service import assign_business_to_affiliate
from platform_affiliates.services.code_generator import generate_affiliate_code
from platform_affiliates.services.commission_service import record_syncworks_revenue_commission
from user_accounts.models import Business


User = get_user_model()


class AffiliateFoundationTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer1",
            email="customer@example.com",
            password="testpass123",
            first_name="Customer",
            last_name="One",
        )

        self.god_user = User.objects.create_user(
            username="godmode1",
            email="jacoblord7@outlook.com",
            password="testpass123",
            first_name="Jacob",
            last_name="Lord",
        )

        self.owner = User.objects.create_user(
            username="owner1",
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="One",
        )

        self.business = Business.objects.create(
            owner=self.owner,
            name="Test Plumbing LLC",
            business_email="owner@example.com",
            owner_name="Owner One",
        )

    def token_client(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    def test_code_auto_generates_swsc_prefix(self):
        code = generate_affiliate_code()
        self.assertTrue(code.startswith("SWSC"))

    def test_affiliate_code_is_unique(self):
        AffiliatePartner.objects.create(
            user=self.customer,
            name="Customer One",
            email="customer@example.com",
            code="SWSC01",
        )

        with self.assertRaises(Exception):
            AffiliatePartner.objects.create(
                name="Duplicate",
                email="duplicate@example.com",
                code="SWSC01",
            )

    def test_one_business_cannot_have_two_attributions(self):
        affiliate_1 = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="a1@example.com",
            code="SWSC01",
        )
        affiliate_2 = AffiliatePartner.objects.create(
            name="Affiliate Two",
            email="a2@example.com",
            code="SWSC02",
        )

        ReferralAttribution.objects.create(
            business=self.business,
            affiliate=affiliate_1,
            referral_code=affiliate_1.code,
            attribution_source=AttributionSource.GODMODE_MANUAL,
        )

        with self.assertRaises(Exception):
            ReferralAttribution.objects.create(
                business=self.business,
                affiliate=affiliate_2,
                referral_code=affiliate_2.code,
                attribution_source=AttributionSource.GODMODE_MANUAL,
            )

    def test_manual_assignment_creates_audit_log(self):
        affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="a1@example.com",
            code="SWSC01",
        )

        attribution = assign_business_to_affiliate(
            business=self.business,
            affiliate=affiliate,
            actor=self.god_user,
            reason="SBO forgot code",
            retroactive=False,
        )

        self.assertEqual(attribution.business, self.business)
        self.assertEqual(attribution.affiliate, affiliate)
        self.assertTrue(
            AffiliateAuditLog.objects.filter(
                action="AFFILIATE_BUSINESS_ASSIGNED",
                affiliate=affiliate,
                business=self.business,
            ).exists()
        )

    def test_commission_only_creates_when_business_has_attribution(self):
        no_commission = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("50.00"),
            source_reference="invoice-no-affiliate",
            revenue_source=RevenueSource.PLATFORM_FEE,
            source_date=timezone.localdate(),
            gross_revenue_amount=Decimal("5000.00"),
        )

        self.assertIsNone(no_commission)

        affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="a1@example.com",
            code="SWSC01",
        )

        assign_business_to_affiliate(
            business=self.business,
            affiliate=affiliate,
            actor=self.god_user,
            reason="Test",
        )

        commission = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("50.00"),
            source_reference="invoice-has-affiliate",
            revenue_source=RevenueSource.PLATFORM_FEE,
            source_date=timezone.localdate(),
            gross_revenue_amount=Decimal("5000.00"),
        )

        self.assertIsNotNone(commission)
        self.assertEqual(commission.commission_amount, Decimal("5.00"))

    def test_duplicate_source_reference_does_not_double_pay(self):
        affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="a1@example.com",
            code="SWSC01",
        )

        assign_business_to_affiliate(
            business=self.business,
            affiliate=affiliate,
            actor=self.god_user,
            reason="Test",
        )

        first = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("50.00"),
            source_reference="invoice-dup",
            revenue_source=RevenueSource.PLATFORM_FEE,
            source_date=timezone.localdate(),
            gross_revenue_amount=Decimal("5000.00"),
        )

        second = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("50.00"),
            source_reference="invoice-dup",
            revenue_source=RevenueSource.PLATFORM_FEE,
            source_date=timezone.localdate(),
            gross_revenue_amount=Decimal("5000.00"),
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(AffiliateCommissionLedger.objects.count(), 1)

    def test_customer_can_apply_for_affiliate_program(self):
        client = self.token_client(self.customer)

        response = client.post(
            reverse("affiliate-me"),
            {
                "name": "Customer One",
                "email": "customer@example.com",
                "phone": "555-111-2222",
                "address_line_1": "123 Main St",
                "city": "Montgomery",
                "state": "AL",
                "zip_code": "36109",
                "payout_provider": "MANUAL",
                "payout_email": "customer@example.com",
                "accepted_agreement": True,
                "referral_strategy": "I will refer local service businesses.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(AffiliatePartner.objects.filter(user=self.customer).exists())

    def test_affiliate_application_creates_agreement_acceptance_snapshot(self):
        client = self.token_client(self.customer)

        response = client.post(
            reverse("affiliate-me"),
            {
                "name": "Customer One",
                "email": "customer@example.com",
                "phone": "555-111-2222",
                "address_line_1": "123 Main St",
                "city": "Montgomery",
                "state": "AL",
                "zip_code": "36109",
                "payout_provider": "MANUAL",
                "payout_email": "customer@example.com",
                "accepted_agreement": True,
                "referral_strategy": "I will refer local service businesses.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        affiliate = AffiliatePartner.objects.get(user=self.customer)

        acceptance = AffiliateAgreementAcceptance.objects.filter(
            affiliate=affiliate,
            user=self.customer,
        ).first()

        self.assertIsNotNone(acceptance)
        self.assertTrue(acceptance.agreement_body_snapshot)
        self.assertEqual(acceptance.agreement_version, affiliate.agreement_version)

    def test_business_owner_cannot_apply_as_customer_affiliate(self):
        client = self.token_client(self.owner)

        response = client.post(
            reverse("affiliate-me"),
            {
                "name": "Owner One",
                "email": "owner@example.com",
                "accepted_agreement": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_non_god_user_cannot_use_godmode_endpoint(self):
        client = self.token_client(self.customer)
        response = client.get(reverse("affiliate-godmode-overview"))
        self.assertEqual(response.status_code, 403)

    def test_godmode_can_create_affiliate(self):
        client = self.token_client(self.god_user)

        response = client.post(
            reverse("affiliate-godmode-affiliates"),
            {
                "name": "God Created Affiliate",
                "email": "affiliate@example.com",
                "status": "ACTIVE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(AffiliatePartner.objects.filter(email="affiliate@example.com").exists())

    def test_godmode_can_assign_business(self):
        affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="a1@example.com",
            code="SWSC01",
        )

        client = self.token_client(self.god_user)

        response = client.post(
            reverse("affiliate-godmode-assign-business"),
            {
                "business_id": self.business.id,
                "affiliate_id": affiliate.id,
                "reason": "SBO forgot code",
                "effective_from": str(timezone.localdate()),
                "retroactive": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ReferralAttribution.objects.filter(
                business=self.business,
                affiliate=affiliate,
            ).exists()
        )