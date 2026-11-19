"""Owner and delegated employee authorization regressions.

Run with: python manage.py test user_accounts.tests.test_ceo_delegation
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from user_accounts.models import Business, BusinessMember


class BusinessDelegationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="ceo", email="ceo@example.test", password="testpass")
        self.hr = User.objects.create_user(username="hr", email="hr@example.test", password="testpass")
        self.tech = User.objects.create_user(username="tech", email="tech@example.test", password="testpass")
        self.stranger = User.objects.create_user(username="stranger", email="stranger@example.test", password="testpass")
        self.business = Business.objects.create(owner=self.owner, name="Solo CEO")
        self.other = Business.objects.create(owner=self.stranger, name="Other Co")
        self.hr_member = BusinessMember.objects.create(
            business=self.business, user=self.hr, role="HR", is_active=True, can_manage_team=True
        )
        self.tech_member = BusinessMember.objects.create(
            business=self.business, user=self.tech, role="TECHNICIAN", is_active=True
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_solo_owner_gets_ceo_context_without_employee_membership(self):
        response = self.client_for(self.owner).get("/api/v1/businesses/access-contexts/")
        self.assertEqual(response.status_code, 200, response.data)
        context = next(item for item in response.data["businesses"] if item["business_id"] == self.business.id)
        self.assertTrue(context["can_access_ceo"])
        self.assertTrue(context["permissions"]["can_manage_team"])
        self.assertFalse(BusinessMember.objects.filter(user=self.owner, business=self.business).exists())

    def test_employee_has_no_ceo_context_and_no_cross_tenant_visibility(self):
        response = self.client_for(self.tech).get("/api/v1/businesses/access-contexts/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([x["business_id"] for x in response.data["businesses"]], [self.business.id])
        self.assertFalse(response.data["businesses"][0]["can_access_ceo"])

    def test_employee_me_endpoint_scopes_to_caller(self):
        response = self.client_for(self.tech).get("/api/v1/business-members/me/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.tech.id)

    def test_hr_cannot_make_owner_or_escalate_protected_access(self):
        client = self.client_for(self.hr)
        url = f"/api/v1/business-members/{self.tech_member.pk}/"
        for payload in (
            {"role": "OWNER"},
            {"role": "MANAGER"},
            {"can_manage_team": True},
            {"can_view_financials": True},
        ):
            result = client.patch(url, payload, format="json")
            self.assertEqual(result.status_code, 403, result.data)

    def test_hr_can_manage_ordinary_employee(self):
        response = self.client_for(self.hr).patch(
            f"/api/v1/business-members/{self.tech_member.pk}/",
            {"can_manage_schedule": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.tech_member.refresh_from_db()
        self.assertTrue(self.tech_member.can_manage_schedule)

    def test_non_owner_cannot_edit_other_tenant_or_own_permissions(self):
        client = self.client_for(self.hr)
        self.assertIn(
            client.patch(f"/api/v1/business-members/{self.hr_member.pk}/", {"role": "MANAGER"}, format="json").status_code,
            (403, 404),
        )
        self.assertIn(
            client.patch(f"/api/v1/businesses/{self.other.pk}/", {"name": "Hijacked"}, format="json").status_code,
            (403, 404),
        )

    def test_owner_can_manage_employee_but_not_edit_own_owner_membership(self):
        client = self.client_for(self.owner)
        response = client.patch(f"/api/v1/business-members/{self.tech_member.pk}/", {"role": "DISPATCH"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.tech_member.refresh_from_db()
        self.assertEqual(self.tech_member.role, "DISPATCH")
        owner_member = BusinessMember.objects.create(business=self.business, user=self.owner, role="OWNER")
        rejected = client.patch(f"/api/v1/business-members/{owner_member.pk}/", {"role": "TECHNICIAN"}, format="json")
        self.assertEqual(rejected.status_code, 403, rejected.data)

    def test_cannot_invite_an_owner_or_admin(self):
        client = self.client_for(self.owner)
        for role in ("OWNER", "ADMIN"):
            result = client.post(
                f"/api/v1/businesses/{self.business.pk}/invite-employee/",
                {"email": "someone@example.test", "role": role},
                format="json",
            )
            self.assertIn(result.status_code, (400, 403), result.data)
