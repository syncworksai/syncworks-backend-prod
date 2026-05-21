from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from platform_affiliates.choices import (
    CommissionStatus,
    PayoutBatchStatus,
    RevenueSource,
)
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    AffiliatePartner,
    AffiliatePayoutBatch,
)
from platform_affiliates.services.attribution_service import (
    assign_business_to_affiliate,
)
from platform_affiliates.services.commission_service import (
    record_syncworks_revenue_commission,
)
from user_accounts.models import Business

User = get_user_model()


class AffiliatePayoutBatchTests(TestCase):
    def setUp(self):
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

        self.affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="affiliate@example.com",
            code="SWSC01",
            status="ACTIVE",
        )

        assign_business_to_affiliate(
            business=self.business,
            affiliate=self.affiliate,
            actor=self.god_user,
            reason="Test payout setup",
        )

    def token_client(self, user):
        token, _ = Token.objects.get_or_create(user=user)

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {token.key}"
        )

        return client

    def seed_commissions(self):
        today = timezone.localdate()

        c1 = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("50.00"),
            source_reference="invoice-platform-fee-001",
            revenue_source=RevenueSource.PLATFORM_FEE,
            source_date=today,
            gross_revenue_amount=Decimal("5000.00"),
        )

        c2 = record_syncworks_revenue_commission(
            business=self.business,
            net_syncworks_revenue_amount=Decimal("19.99"),
            source_reference="subscription-sbo-001",
            revenue_source=RevenueSource.SBO_SUBSCRIPTION,
            source_date=today,
            gross_revenue_amount=Decimal("19.99"),
        )

        return c1, c2

    def test_godmode_can_create_payout_batch(self):
        self.seed_commissions()

        client = self.token_client(self.god_user)

        today = timezone.localdate()

        response = client.post(
            "/api/v1/platform-affiliates/godmode/payout-batches/",
            {
                "affiliate_id": self.affiliate.id,
                "period_start": str(today.replace(day=1)),
                "period_end": str(today),
                "notes": "May payout draft",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(
            AffiliatePayoutBatch.objects.count(),
            1,
        )

        batch = AffiliatePayoutBatch.objects.first()

        self.assertEqual(
            batch.affiliate,
            self.affiliate,
        )

        self.assertEqual(
            batch.status,
            PayoutBatchStatus.DRAFT,
        )

        self.assertEqual(
            batch.total_amount,
            Decimal("7.00"),
        )

        linked = AffiliateCommissionLedger.objects.filter(
            payout_batch=batch
        )

        self.assertEqual(
            linked.count(),
            2,
        )

        self.assertTrue(
            linked.filter(
                status=CommissionStatus.APPROVED
            ).exists()
        )

    def test_godmode_can_mark_payout_batch_paid(self):
        self.seed_commissions()

        client = self.token_client(self.god_user)

        today = timezone.localdate()

        create_response = client.post(
            "/api/v1/platform-affiliates/godmode/payout-batches/",
            {
                "affiliate_id": self.affiliate.id,
                "period_start": str(today.replace(day=1)),
                "period_end": str(today),
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            201,
        )

        batch_id = create_response.data["id"]

        paid_response = client.post(
            f"/api/v1/platform-affiliates/godmode/payout-batches/{batch_id}/mark-paid/",
            {
                "external_reference": "manual-check-1001",
                "notes": "Paid manually",
            },
            format="json",
        )

        self.assertEqual(
            paid_response.status_code,
            200,
        )

        batch = AffiliatePayoutBatch.objects.get(
            id=batch_id
        )

        self.assertEqual(
            batch.status,
            PayoutBatchStatus.PAID,
        )

        self.assertEqual(
            batch.external_reference,
            "manual-check-1001",
        )

        self.assertIsNotNone(
            batch.paid_at
        )

        self.assertEqual(
            AffiliateCommissionLedger.objects.filter(
                payout_batch=batch,
                status=CommissionStatus.PAID,
            ).count(),
            2,
        )