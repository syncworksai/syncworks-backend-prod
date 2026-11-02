"""Regression tests for the three Jarvis intake paths and PM write approval."""
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from pm_workspace.models import PMProperty, PMWorkspace
from pm_workspace.workorder_models import PMWorkOrder
from user_accounts.models import AuditLog, Business


class JarvisWorkflowIntakeTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="jarvis-owner", email="jarvis-owner@example.com", password="test-password-123"
        )
        self.other = get_user_model().objects.create_user(
            username="jarvis-other", email="jarvis-other@example.com", password="test-password-123"
        )
        self.portfolio = PMWorkspace.objects.create(owner=self.user, name="Test PM")
        self.property = PMProperty.objects.create(
            workspace=self.portfolio,
            name="Test Rental",
            address="100 Example Lane",
            city="Montgomery",
            state="AL",
            zip="36104",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def test_requires_authentication(self):
        self.client.credentials()
        response = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"description": "Need a mobile notary tomorrow."},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_service_preview_does_not_create_work_order(self):
        response = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"workspace": "personal", "workflow_type": "service_booking", "description": "Need a mobile notary tomorrow near my office."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["workflow_type"], "service_booking")
        self.assertEqual(response.data["route"], "/customer/new-request")
        self.assertFalse(response.data["executed"])
        self.assertEqual(PMWorkOrder.objects.count(), 0)

    def test_business_lead_is_owner_scoped(self):
        business = Business.objects.create(owner=self.user, name="Test Sales Business")
        valid = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"workspace": "business", "business_id": business.id, "workflow_type": "sales_lead", "description": "A customer wants to learn about day trading education."},
            format="json",
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.data["route"], "/sbo/leads")
        self.assertFalse(valid.data["executed"])
        forbidden = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"workspace": "business", "business_id": Business.objects.create(owner=self.other, name="Private Business").id, "workflow_type": "sales_lead", "description": "A lead is interested in education."},
            format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_pm_preview_scoped_to_portfolio(self):
        response = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"workspace": "pm", "workflow_type": "maintenance", "description": "Tenant reports a leaking kitchen sink."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["priority_suggestion"], "HIGH")
        self.assertEqual(response.data["category_suggestion"], "PLUMBING")
        self.assertEqual(response.data["properties"][0]["id"], self.property.id)
        self.assertTrue(response.data["can_create_pm_work_order"])
        self.assertEqual(PMWorkOrder.objects.count(), 0)

    def test_pm_confirmed_creation_is_scoped_and_audited(self):
        path = "/api/v1/sync-ai/workflows/pm-work-order/create/"
        body = {
            "workspace": "pm", "confirmed": True,
            "property_id": self.property.id, "title": "Leaking kitchen sink",
            "description": "Tenant reports leaking water under the kitchen sink.",
        }
        denied = self.client.post(path, {**body, "confirmed": False}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(PMWorkOrder.objects.count(), 0)

        created = self.client.post(path, body, format="json")
        self.assertEqual(created.status_code, 201)
        order = PMWorkOrder.objects.get(pk=created.data["id"])
        self.assertEqual(order.property_id, self.property.id)
        self.assertEqual(order.status, PMWorkOrder.Status.TRIAGE)
        self.assertEqual(order.priority, PMWorkOrder.Priority.HIGH)
        self.assertIsNone(order.marketplace_ticket_id)
        self.assertTrue(AuditLog.objects.filter(actor=self.user, action="sync_ai.pm_work_order_created").exists())

    def test_other_portfolio_is_forbidden(self):
        other_portfolio = PMWorkspace.objects.create(owner=self.other, name="Other Portfolio")
        other_property = PMProperty.objects.create(
            workspace=other_portfolio, name="Private Rental", address="200 Other St",
            city="Montgomery", state="AL", zip="36104",
        )
        path = "/api/v1/sync-ai/workflows/pm-work-order/create/"
        body = {"workspace": "pm", "confirmed": True, "title": "Leaking kitchen sink",
                "description": "Tenant reports water leaking under kitchen sink."}
        forbidden = self.client.post(path, {**body, "pm_workspace_id": other_portfolio.id, "property_id": other_property.id}, format="json")
        self.assertEqual(forbidden.status_code, 403)
        wrong_property = self.client.post(path, {**body, "property_id": other_property.id}, format="json")
        self.assertEqual(wrong_property.status_code, 400)
        self.assertEqual(PMWorkOrder.objects.count(), 0)

    def test_emergency_advisory_does_not_dispatch(self):
        response = self.client.post(
            "/api/v1/sync-ai/workflows/preview/",
            {"workspace": "pm", "workflow_type": "maintenance",
             "description": "Tenant can smell gas near the kitchen stove."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["priority_suggestion"], "EMERGENCY")
        self.assertTrue(response.data["safety_alert"])
        self.assertEqual(PMWorkOrder.objects.count(), 0)
