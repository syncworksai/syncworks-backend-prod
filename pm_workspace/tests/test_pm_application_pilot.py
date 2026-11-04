"""Synthetic, nonfinancial PM lead-to-application onboarding tests."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from pm_workspace.lead_models import PMLead
from pm_workspace.models import PMProperty, PMWorkspace, PMLedgerEntry


User = get_user_model()


class PMApplicationPilotTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner-onboarding", email="owner-pm@example.com", password="test-password-not-prod"
        )
        self.applicant = User.objects.create_user(
            username="applicant-onboarding", email="applicant-pm@example.com", password="test-password-not-prod"
        )
        self.stranger = User.objects.create_user(
            username="stranger-onboarding", email="other-pm@example.com", password="test-password-not-prod"
        )
        self.ws = PMWorkspace.objects.create(owner=self.owner, name="Test Onboarding PM")
        self.property = PMProperty.objects.create(
            workspace=self.ws, name="Test Oak", address="100 Oak Road",
            city="Montgomery", state="AL", zip="36104", created_by=self.owner,
        )
        self.lead = PMLead.objects.create(
            workspace=self.ws, first_name="Applicant", last_name="Pilot",
            email=self.applicant.email, source="PHONE", created_by=self.owner,
        )
        self.headers = {"HTTP_X_PM_WORKSPACE_ID": str(self.ws.id)}
        self.client.force_authenticate(self.owner)

    def test_phone_lead_can_apply_before_property_then_link_it(self):
        url = f"/api/v1/pm-hub/onboarding/leads/{self.lead.id}/profile/"
        data = self.client.patch(url, {
            "section8_requested": True, "voucher_amount": "1750",
            "voucher_bedrooms": 3, "agency_name": "Local housing authority",
            "agent_name": "Agent Example", "agent_email": "agent@example.org",
        }, format="json", **self.headers)
        self.assertEqual(data.status_code, 200, data.data)
        self.assertIsNone(self.lead.property_id)
        self.assertEqual(data.data["voucher_amount"], "1750.00")
        invitation = self.client.post(
            f"/api/v1/pm-hub/onboarding/leads/{self.lead.id}/invite/",
            {}, format="json", **self.headers,
        )
        self.assertEqual(invitation.status_code, 201, invitation.data)
        token = invitation.data["application_path"].split("token=", 1)[1]
        self.client.force_authenticate(self.stranger)
        denied = self.client.get("/api/v1/pm-hub/onboarding/applications/my/", {"token": token})
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.applicant)
        preview = self.client.get("/api/v1/pm-hub/onboarding/applications/my/", {"token": token})
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["property_id"])
        applied = self.client.post("/api/v1/pm-hub/onboarding/applications/my/", {
            "token": token, "property_id": self.property.id,
            "section8_requested": True, "voucher_amount": "1750",
            "agent_email": "agent@example.org",
            "adults": 2, "children": 1,
            "preferred_contact": "EMAIL", "phone": "555-0101",
            "preferred_move_in": "2027-01-15",
        }, format="json")
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(applied.data["application_status"], "SUBMITTED")
        self.assertEqual(applied.data["property_id"], self.property.id)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.stage, PMLead.Stage.APPLICATION)
        self.assertEqual(self.lead.source, "PHONE")
        self.assertEqual(self.lead.metadata["pm_onboarding"]["voucher_amount"], "1750.00")
        self.assertEqual(self.lead.metadata["pm_onboarding"]["agent_email"], "agent@example.org")
        duplicate = self.client.post(
            "/api/v1/pm-hub/onboarding/applications/my/", {"token": token, "adults": 3}, format="json"
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(PMLedgerEntry.objects.count(), 0)
        self.client.force_authenticate(self.owner)
        overview = self.client.get("/api/v1/pm-hub/onboarding/overview/", **self.headers)
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.data["applications_submitted"], 1)
        self.assertEqual(overview.data["properties"][0]["inquiries"], 1)

    def test_invitation_replaced_and_property_data_not_billing(self):
        url = f"/api/v1/pm-hub/onboarding/leads/{self.lead.id}/invite/"
        first = self.client.post(url, {}, format="json", **self.headers)
        new = self.client.post(url, {}, format="json", **self.headers)
        old_token = first.data["application_path"].split("token=", 1)[1]
        self.client.force_authenticate(self.applicant)
        denied = self.client.get("/api/v1/pm-hub/onboarding/applications/my/", {"token": old_token})
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.owner)
        housing = self.client.patch(
            f"/api/v1/pm-hub/onboarding/properties/{self.property.id}/housing/",
            {"accepts_section8": True, "proposed_rent": "1485", "voucher_payment_standard": "1800",
             "approved_hap_share": "", "approval_status": "UNVERIFIED",
             "housing_authority": "Housing Agency"},
            format="json", **self.headers,
        )
        self.assertEqual(housing.status_code, 200, housing.data)
        self.assertEqual(housing.data["section8_pricing"]["proposed_rent"], "1485.00")
        self.assertEqual(housing.data["section8_pricing"]["voucher_payment_standard"], "1800.00")
        self.assertEqual(PMLedgerEntry.objects.count(), 0)
        other = User.objects.create_user(
            username="other-owner-onboard", email="other-owner@example.com", password="test-password"
        )
        other_ws = PMWorkspace.objects.create(owner=other, name="Other Test PM")
        self.client.force_authenticate(other)
        forbidden = self.client.get(
            f"/api/v1/pm-hub/onboarding/leads/{self.lead.id}/profile/",
            HTTP_X_PM_WORKSPACE_ID=str(other_ws.id),
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_bad_voucher_and_email_do_not_mutate_lead(self):
        url = f"/api/v1/pm-hub/onboarding/leads/{self.lead.id}/profile/"
        result = self.client.patch(url, {
            "voucher_amount": "-50", "agent_email": "bad-email",
        }, format="json", **self.headers)
        self.assertEqual(result.status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.metadata, {})
