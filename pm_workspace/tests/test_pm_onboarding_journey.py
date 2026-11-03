"""Repeatable synthetic onboarding journey, never using live Roxana records."""
from datetime import date
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from pm_workspace.document_models import PMPropertyDocument
from pm_workspace.lifecycle_models import PMOccupancy
from pm_workspace.models import PMProperty, PMWorkspace
from pm_workspace.private_document_storage import pm_document_storage


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_BASE_URL="https://syncworksapp.com",
)
class PMOnboardingJourneyTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="pm-journey-owner", email="pm-journey-owner@example.com",
            password="test-only-journey-password",
        )
        self.resident = get_user_model().objects.create_user(
            username="pm-journey-tenant", email="pm-journey-tenant@example.com",
            password="test-only-journey-password",
        )
        self.ws = PMWorkspace.objects.create(owner=self.owner, name="Test Portfolio")
        self.headers = {"HTTP_X_PM_WORKSPACE_ID": str(self.ws.id)}
        self.client.force_authenticate(self.owner)

    def test_property_application_lease_document_invite_payment_and_maintenance(self):
        # One synthetic case traverses owner + resident endpoints in a temporary DB.
        today = timezone.localdate()
        due = today.replace(day=1)
        prop = self.client.post("/api/v1/pm-hub/properties/", {
            "name": "Test Maple", "address": "42 Maple Avenue",
            "city": "Montgomery", "state": "AL", "zip": "36104",
        }, format="json", **self.headers)
        self.assertEqual(prop.status_code, 201, prop.data)
        property_id = prop.data["id"]

        unit = self.client.post("/api/v1/pm-hub/units/", {
            "property": property_id, "label": "Unit A", "market_rent": "1485.00",
        }, format="json", **self.headers)
        self.assertEqual(unit.status_code, 201, unit.data)
        unit_id = unit.data["id"]

        prospect = self.client.post("/api/v1/pm-hub/prospects/", {
            "first_name": "Morgan", "last_name": "Example",
            "email": "pm-journey-tenant@example.com", "assigned_unit": unit_id,
            "stage": "LEAD",
        }, format="json", **self.headers)
        self.assertEqual(prospect.status_code, 201, prospect.data)
        prospect_id = prospect.data["id"]

        stage = self.client.patch(f"/api/v1/pm-hub/prospects/{prospect_id}/", {
            "stage": "APPLICATION_RECEIVED",
        }, format="json", **self.headers)
        self.assertEqual(stage.status_code, 200, stage.data)
        approved = self.client.patch(f"/api/v1/pm-hub/prospects/{prospect_id}/", {
            "stage": "APPROVED",
        }, format="json", **self.headers)
        self.assertEqual(approved.status_code, 200, approved.data)
        converted = self.client.post(
            f"/api/v1/pm-hub/prospects/{prospect_id}/convert-to-tenant/",
            {}, format="json", **self.headers,
        )
        self.assertEqual(converted.status_code, 201, converted.data)
        tenant_id = converted.data["id"]

        lease = self.client.post("/api/v1/pm-hub/leases/", {
            "tenant": tenant_id, "unit": unit_id, "term": "MONTH_TO_MONTH",
            "start_date": due.isoformat(), "monthly_rent": "1485.00",
            "status": "ACTIVE",
        }, format="json", **self.headers)
        self.assertEqual(lease.status_code, 201, lease.data)
        self.assertTrue(PMOccupancy.objects.filter(
            tenant_id=tenant_id, property_id=property_id,
            status=PMOccupancy.Status.ACTIVE,
        ).exists())

        with tempfile.TemporaryDirectory() as media_dir:
            with override_settings(MEDIA_ROOT=media_dir):
                uploaded = self.client.post("/api/v1/pm-hub/property-documents/", {
                    "property": property_id, "tenant": tenant_id,
                    "lease": lease.data["id"], "category": "LEASE",
                    "title": "Signed synthetic lease",
                    "document": SimpleUploadedFile(
                        "test-lease.txt", b"Monthly rent $1485; due on the 1st",
                        content_type="text/plain",
                    ),
                }, format="multipart", **self.headers)
                self.assertEqual(uploaded.status_code, 201, uploaded.data)
                record = PMPropertyDocument.objects.get(pk=uploaded.data["id"])
                with record.document.open("rb") as saved:
                    self.assertIn(b"Monthly rent", saved.read())
                docs = self.client.get(
                    f"/api/v1/pm-hub/property-documents/?property_id={property_id}",
                    **self.headers,
                )
                self.assertEqual(docs.status_code, 200, docs.data)

        invitation = self.client.post(
            f"/api/v1/pm-hub/tenants/{tenant_id}/send-invite/",
            {"mode": "TENANT_ONBOARDING"}, format="json", **self.headers,
        )
        self.assertEqual(invitation.status_code, 201, invitation.data)
        self.assertEqual(len(mail.outbox), 1)
        from pm_workspace.models import PMTenantInvitation
        token = PMTenantInvitation.objects.get(pk=invitation.data["id"]).code
        self.client.force_authenticate(self.resident)
        accepted = self.client.post(
            "/api/v1/pm-hub/tenant-invitations/accept/",
            {"code": token}, format="json",
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)

        account = self.client.get("/api/v1/pm-hub/billing/my-account/")
        self.assertEqual(account.status_code, 200, account.data)
        self.assertEqual(account.data["property_name"], "Test Maple")
        self.assertEqual(account.data["lease"]["monthly_rent"], "1485.00")

        maintenance = self.client.post(
            "/api/v1/pm-hub/tenant-portal/communications/",
            {"action": "MAINTENANCE", "subject": "Test sink leak",
             "description": "Sink leaking near the cabinet", "category": "PLUMBING",
             "priority": "ROUTINE", "permission_to_enter": False},
            format="json",
        )
        self.assertEqual(maintenance.status_code, 201, maintenance.data)

        self.client.force_authenticate(self.owner)
        orders = self.client.get(
            "/api/v1/pm-hub/work-orders/", **self.headers,
        )
        self.assertEqual(orders.status_code, 200, orders.data)

        charge = self.client.post("/api/v1/pm-hub/ledger/", {
            "tenant": tenant_id, "lease": lease.data["id"],
            "entry_date": due.isoformat(), "entry_type": "CHARGE",
            "category": "RENT_TENANT", "amount": "1485.00",
        }, format="json", **self.headers)
        self.assertEqual(charge.status_code, 201, charge.data)
        payment = self.client.post("/api/v1/pm-hub/ledger/", {
            "tenant": tenant_id, "lease": lease.data["id"],
            "entry_date": today.isoformat(), "entry_type": "PAYMENT",
            "category": "RENT_TENANT", "amount": "400.00",
            "payment_method": "OTHER", "reference": "TEST-MANUAL-RECEIPT",
        }, format="json", **self.headers)
        self.assertEqual(payment.status_code, 201, payment.data)
        self.client.force_authenticate(self.resident)
        after = self.client.get("/api/v1/pm-hub/billing/my-account/")
        self.assertEqual(after.status_code, 200, after.data)
        self.assertEqual(after.data["account"]["amount_due"], "1085.00")

    def test_private_r2_adapter_requires_complete_configuration(self):
        with patch.dict(os.environ, {"PM_R2_STORAGE_ENABLED": "true"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                pm_document_storage()
        with patch.dict(os.environ, {
            "PM_R2_STORAGE_ENABLED": "true",
            "PM_R2_BUCKET": "test-private",
            "PM_R2_ENDPOINT_URL": "http://r2.example.test",
            "PM_R2_ACCESS_KEY_ID": "test",
            "PM_R2_SECRET_ACCESS_KEY": "test",
        }, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                pm_document_storage()

    def test_other_portfolio_cannot_read_private_property_document_metadata(self):
        outside = get_user_model().objects.create_user(
            username="pm-unrelated", email="unrelated@example.com",
            password="test-only-journey-password",
        )
        outside_ws = PMWorkspace.objects.create(owner=outside, name="Other Portfolio")
        property_obj = PMProperty.objects.create(
            workspace=self.ws, name="Private Road", address="1 Private Road",
            city="Montgomery", state="AL", zip="36104",
        )
        doc = PMPropertyDocument.objects.create(
            workspace=self.ws, property=property_obj, category="LEASE",
            title="Confidential test document", source_url="https://example.com/unrelated-source.pdf",
        )
        self.client.force_authenticate(outside)
        r = self.client.get(
            f"/api/v1/pm-hub/property-documents/{doc.pk}/",
            HTTP_X_PM_WORKSPACE_ID=str(outside_ws.pk),
        )
        self.assertEqual(r.status_code, 404)
