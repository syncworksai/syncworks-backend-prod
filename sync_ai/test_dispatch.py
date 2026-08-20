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
class DispatchTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dispatch-owner", email="dispatch@example.com", password="test-password-123")
        token = Token.objects.create(user=self.user)
        self.business = Business.objects.create(owner=self.user, name="Route Test Co", base_zip="36104", accepts_marketplace_tickets=True)
        self.member = BusinessMember.objects.create(business=self.business, user=self.user, role="OWNER", is_active=True, can_manage_schedule=True, can_assign_tickets=True)
        WorkforceProfile.objects.create(member=self.member, title="Lead Tech", skills=["Plumbing"], route_start_address="100 Main St, Montgomery, AL", default_buffer_minutes=10, is_schedulable=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))

    def make_job(self, start, end, address="200 Market St, Montgomery, AL"):
        req = ServiceRequest.objects.create(customer=self.user, title="Repair", description="Test", address=address, zip_code="36104", status="MATCHED", target_business=self.business)
        ticket = Ticket.objects.create(service_request=req, customer=self.user, assigned_business=self.business, assigned_member=self.user, service_address=address, service_zip="36104", status="SCHEDULED", scheduled_at=start)
        TicketOperationalProfile.objects.create(ticket=ticket, origin="MARKETPLACE", priority="STANDARD", scheduled_start=start, scheduled_end=end, expected_finish_at=end, due_at=end + timedelta(hours=2))
        return ticket

    @patch("sync_ai.dispatch_views.estimate_travel", return_value={"minutes": 20, "miles": 8.0, "basis": "test"})
    def test_dispatch_board_flags_insufficient_travel_gap(self, travel):
        day = timezone.localdate() + timedelta(days=1)
        first = timezone.make_aware(datetime.combine(day, time(9, 0)))
        second = timezone.make_aware(datetime.combine(day, time(10, 5)))
        self.make_job(first, first + timedelta(hours=1), "200 Market St")
        self.make_job(second, second + timedelta(hours=1), "300 Pine St")
        response = self.client.get(f"/api/v1/sync-ai/business/dispatch/?date={day.isoformat()}")
        self.assertEqual(response.status_code, 200)
        jobs = response.data["staff"][0]["jobs"]
        self.assertFalse(jobs[0]["route_conflict"])
        self.assertTrue(jobs[1]["route_conflict"])
        self.assertEqual(jobs[1]["risk"], "AT_RISK")

    def test_delay_updates_expected_finish_without_moving_later_jobs(self):
        day = timezone.localdate() + timedelta(days=1)
        start = timezone.make_aware(datetime.combine(day, time(11, 0)))
        ticket = self.make_job(start, start + timedelta(hours=1))
        original = ticket.operations_profile.scheduled_end
        response = self.client.post(f"/api/v1/sync-ai/business/dispatch/{ticket.id}/delay/", {"minutes": 30}, format="json")
        self.assertEqual(response.status_code, 200)
        ticket.operations_profile.refresh_from_db()
        self.assertEqual(ticket.operations_profile.scheduled_end, original + timedelta(minutes=30))
        self.assertEqual(ticket.operations_profile.expected_finish_at, original + timedelta(minutes=30))
        self.assertIn("moved automatically", response.data["message"])
