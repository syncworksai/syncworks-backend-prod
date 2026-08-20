from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import Business, BusinessMember, ServiceRequest, Ticket, TicketOperationalProfile, WorkforceProfile


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class LiveOperationsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="field-tech", email="tech@example.com", password="test-password-123")
        self.owner = get_user_model().objects.create_user(username="ops-owner", email="owner@example.com", password="test-password-123")
        self.business = Business.objects.create(owner=self.owner, name="Live Ops Co", base_zip="36104", accepts_marketplace_tickets=True)
        self.member = BusinessMember.objects.create(business=self.business, user=self.user, role="TECHNICIAN", is_active=True, can_manage_schedule=False)
        self.owner_member = BusinessMember.objects.create(business=self.business, user=self.owner, role="OWNER", is_active=True, can_manage_schedule=True, can_assign_tickets=True)
        WorkforceProfile.objects.create(member=self.member, title="Field Tech", skills=["Plumbing"], route_start_address="100 Main St", default_buffer_minutes=10, is_schedulable=True)
        WorkforceProfile.objects.create(member=self.owner_member, title="Owner", route_start_address="100 Main St", is_schedulable=False)
        self.tech_token = Token.objects.create(user=self.user)
        self.owner_token = Token.objects.create(user=self.owner)

    def make_job(self, start_hour=9, address="200 Market St"):
        day = timezone.localdate()
        start = timezone.make_aware(datetime.combine(day, time(start_hour, 0)))
        req = ServiceRequest.objects.create(customer=self.owner, title="Repair", description="Test", address=address, zip_code="36104", status="MATCHED", target_business=self.business)
        ticket = Ticket.objects.create(service_request=req, customer=self.owner, assigned_business=self.business, assigned_member=self.user, service_address=address, service_zip="36104", status="SCHEDULED", scheduled_at=start)
        TicketOperationalProfile.objects.create(ticket=ticket, origin="MARKETPLACE", priority="STANDARD", scheduled_start=start, scheduled_end=start + timedelta(hours=1), expected_finish_at=start + timedelta(hours=1), due_at=start + timedelta(hours=3))
        return ticket

    @patch("sync_ai.live_operations_views.weather_for_address", return_value={"available": True, "condition": "Clear", "scheduled": {"precip_probability": 5}})
    @patch("sync_ai.live_operations_views.live_travel", return_value={"minutes": 12, "miles": 5.0, "basis": "google_live_traffic", "traffic_delay_minutes": 2})
    def test_employee_live_day_contains_travel_weather_and_clock(self, travel, weather):
        ticket = self.make_job()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tech_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        response = self.client.get("/api/v1/sync-ai/employee/live-day/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["jobs"][0]["ticket_id"], ticket.id)
        self.assertEqual(response.data["jobs"][0]["travel"]["basis"], "google_live_traffic")
        self.assertEqual(response.data["jobs"][0]["weather"]["condition"], "Clear")
        self.assertFalse(response.data["jobs"][0]["clock"]["running"])

    def test_job_clock_start_and_finish_persist(self):
        ticket = self.make_job()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tech_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        start = self.client.post(f"/api/v1/sync-ai/employee/jobs/{ticket.id}/clock/", {"action": "start"}, format="json")
        self.assertEqual(start.status_code, 200)
        self.assertTrue(start.data["clock"]["running"])
        self.assertEqual(start.data["status"], "IN_PROGRESS")
        finish = self.client.post(f"/api/v1/sync-ai/employee/jobs/{ticket.id}/clock/", {"action": "finish"}, format="json")
        self.assertEqual(finish.status_code, 200)
        self.assertFalse(finish.data["clock"]["running"])
        self.assertEqual(finish.data["status"], "COMPLETED")

    def test_technician_cannot_run_two_clocks(self):
        first = self.make_job(9, "200 Market St")
        second = self.make_job(11, "300 Pine St")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.tech_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        self.client.post(f"/api/v1/sync-ai/employee/jobs/{first.id}/clock/", {"action": "start"}, format="json")
        response = self.client.post(f"/api/v1/sync-ai/employee/jobs/{second.id}/clock/", {"action": "start"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["active_ticket_id"], first.id)

    @patch("sync_ai.live_operations_views.weather_for_address", return_value={"available": True, "condition": "Rain", "scheduled": {"precip_probability": 80}})
    @patch("sync_ai.live_operations_views.live_travel", return_value={"minutes": 28, "miles": 8.0, "basis": "google_live_traffic", "traffic_delay_minutes": 12})
    def test_owner_live_ops_receives_traffic_and_weather_recommendations(self, travel, weather):
        self.make_job()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.owner_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        response = self.client.get("/api/v1/sync-ai/business/live-operations/")
        self.assertEqual(response.status_code, 200)
        types = {row["type"] for row in response.data["recommendations"]}
        self.assertIn("TRAFFIC", types)
        self.assertIn("WEATHER", types)
