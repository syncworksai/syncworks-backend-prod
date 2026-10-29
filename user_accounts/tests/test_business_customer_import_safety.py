"""Pilot regression checks for real customer CSV import, review/execute and access isolation."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from user_accounts.models import Business, BusinessCustomer, BusinessMember

User = get_user_model()


class BusinessCustomerImportSafetyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="csv-owner", email="csv-owner@example.com", password="StrongPassword!123")
        self.staff = User.objects.create_user(username="csv-staff", email="csv-staff@example.com", password="StrongPassword!123")
        self.other = User.objects.create_user(username="csv-other", email="csv-other@example.com", password="StrongPassword!123")
        self.business = Business.objects.create(name="Test Import Services", owner=self.owner)
        BusinessMember.objects.create(business=self.business, user=self.staff, role=BusinessMember.ROLE_TECH, is_active=True)
        self.client = APIClient()
        self.header = {"HTTP_X_BUSINESS_ID": str(self.business.pk)}

    def _preview(self, csv_text, actor=None):
        self.client.force_authenticate(user=actor or self.owner)
        file = SimpleUploadedFile("customers.csv", csv_text.encode("utf-8"), content_type="text/csv")
        return self.client.post("/api/v1/business-data-imports/preview/", {
            "import_type": "CUSTOMERS", "source_system": "Prior CRM", "file": file,
        }, format="multipart", **self.header)

    def test_owner_previews_then_confirms_without_duplicate_customers(self):
        raw = "name,email,phone,service_address,city,state,service_zip\nCustomer A,a@example.com,5551200001,123 Main,Montgomery,AL,36104\nCustomer B,b@example.com,5551200002,234 Main,Montgomery,AL,36104\n"
        preview = self._preview(raw)
        self.assertEqual(preview.status_code, 201, preview.data)
        self.assertEqual(preview.data["status"], "READY")
        self.assertEqual(preview.data["valid_rows"], 2)
        self.assertEqual(BusinessCustomer.objects.filter(business=self.business).count(), 0)
        path = f"/api/v1/business-data-imports/{preview.data['id']}/execute/"
        without_confirm = self.client.post(path, {}, format="json", **self.header)
        self.assertEqual(without_confirm.status_code, 400)
        confirmed = self.client.post(path, {"confirm": True}, format="json", **self.header)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["imported_rows"], 2)
        self.assertEqual(BusinessCustomer.objects.filter(business=self.business).count(), 2)
        again = self._preview(raw)
        self.assertEqual(again.status_code, 201)
        confirmed_again = self.client.post(f"/api/v1/business-data-imports/{again.data['id']}/execute/", {"confirm": True}, format="json", **self.header)
        self.assertEqual(confirmed_again.status_code, 200, confirmed_again.data)
        self.assertEqual(confirmed_again.data["matched_rows"], 2)
        self.assertEqual(BusinessCustomer.objects.filter(business=self.business).count(), 2)

    def test_existing_live_customer_remains_eligible_for_kpis(self):
        live = BusinessCustomer.objects.create(
            business=self.business, name="Existing Customer", email="existing@example.com",
            record_source=BusinessCustomer.RecordSource.MANUAL, exclude_from_kpis=False,
            created_by=self.owner, ticket_count=2,
        )
        preview = self._preview("name,email,phone\nExisting Customer,existing@example.com,5558880000\n")
        result = self.client.post(f"/api/v1/business-data-imports/{preview.data['id']}/execute/", {"confirm": True}, format="json", **self.header)
        self.assertEqual(result.status_code, 200, result.data)
        live.refresh_from_db()
        self.assertEqual(live.ticket_count, 2)
        self.assertFalse(live.exclude_from_kpis)
        self.assertFalse(live.is_imported)
        self.assertEqual(live.record_source, BusinessCustomer.RecordSource.MANUAL)
        self.assertEqual(live.normalized_phone, "5558880000")

    def test_technician_cannot_bulk_import_and_outsider_cannot_access_business(self):
        raw = "name,email\nPerson A,a@example.com\n"
        denied = self._preview(raw, actor=self.staff)
        self.assertEqual(denied.status_code, 403, denied.data)
        denied_other = self._preview(raw, actor=self.other)
        self.assertIn(denied_other.status_code, (403, 404))
        self.assertEqual(BusinessCustomer.objects.count(), 0)
