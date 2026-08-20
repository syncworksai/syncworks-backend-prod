from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import (
    Business,
    BusinessMember,
    ServiceCategory,
    Ticket,
    TicketOperationalProfile,
    WorkforceProfile,
)


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class MarketplaceAvailabilityTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username="market-customer", email="customer@market.test", password="test-password-123")
        self.owner = User.objects.create_user(username="market-owner", email="owner@market.test", password="test-password-123")
        self.tech = User.objects.create_user(username="market-tech", email="tech@market.test", password="test-password-123")
        token = Token.objects.create(user=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        self.category = ServiceCategory.objects.create(name="Water Heater Repair")
        self.business = Business.objects.create(
            owner=self.owner,
            name="Reliable Plumbing",
            base_zip="36104",
            accepts_marketplace_tickets=True,
        )
        self.business.services_offered.add(self.category)
        self.member = BusinessMember.objects.create(
            business=self.business,
            user=self.tech,
            role="TECHNICIAN",
            is_active=True,
        )
        every_day = {
            day: {"open": True, "start": "00:00", "end": "23:59"}
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        }
        WorkforceProfile.objects.create(
            member=self.member,
            title="Plumbing Technician",
            skills=["Water Heater Repair", "water heater"],
            weekly_availability=every_day,
            default_job_duration_minutes=60,
            default_buffer_minutes=15,
            is_schedulable=True,
        )

    def test_marketplace_availability_returns_matching_business_and_staff_slot(self):
        response = self.client.get(
            f"/api/v1/sync-ai/marketplace/availability/?category_id={self.category.id}&zip_code=36104&duration_minutes=60"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["business_id"], self.business.id)
        self.assertEqual(row["matching_staff_count"], 1)
        self.assertTrue(row["slots"])
        self.assertEqual(row["slots"][0]["member_id"], self.member.id)

    def test_booking_creates_marketplace_ticket_with_sla_and_origin(self):
        availability = self.client.get(
            f"/api/v1/sync-ai/marketplace/availability/?category_id={self.category.id}&zip_code=36104&duration_minutes=60"
        )
        slot = availability.data["results"][0]["slots"][0]
        response = self.client.post(
            "/api/v1/sync-ai/marketplace/book/",
            {
                "business_id": self.business.id,
                "category_id": self.category.id,
                "member_id": self.member.id,
                "start": slot["start"],
                "end": slot["end"],
                "priority": "URGENT",
                "title": "Water heater leaking",
                "description": "Leak at the base of the water heater.",
                "address": "100 Main St, Montgomery, AL",
                "zip_code": "36104",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(id=response.data["ticket_id"])
        ops = TicketOperationalProfile.objects.get(ticket=ticket)
        self.assertTrue(ticket.is_marketplace)
        self.assertEqual(ticket.assigned_business_id, self.business.id)
        self.assertEqual(ticket.assigned_member_id, self.tech.id)
        self.assertEqual(ticket.status, Ticket.Status.SCHEDULED)
        self.assertEqual(ops.origin, TicketOperationalProfile.Origin.MARKETPLACE)
        self.assertEqual(ops.priority, TicketOperationalProfile.Priority.URGENT)
        self.assertEqual(ops.response_sla_minutes, 15)
        self.assertIsNotNone(ops.scheduled_start)
        self.assertIsNotNone(ops.scheduled_end)

    def test_double_booking_same_staff_window_is_rejected(self):
        availability = self.client.get(
            f"/api/v1/sync-ai/marketplace/availability/?category_id={self.category.id}&zip_code=36104&duration_minutes=60"
        )
        slot = availability.data["results"][0]["slots"][0]
        payload = {
            "business_id": self.business.id,
            "category_id": self.category.id,
            "member_id": self.member.id,
            "start": slot["start"],
            "end": slot["end"],
            "priority": "STANDARD",
            "title": "First job",
            "address": "100 Main St",
            "zip_code": "36104",
        }
        first = self.client.post("/api/v1/sync-ai/marketplace/book/", payload, format="json")
        self.assertEqual(first.status_code, 201)
        payload["title"] = "Second job"
        second = self.client.post("/api/v1/sync-ai/marketplace/book/", payload, format="json")
        self.assertEqual(second.status_code, 409)

    def test_marketplace_search_excludes_business_without_configured_capacity(self):
        empty = Business.objects.create(owner=self.owner, name="No Capacity Co", base_zip="36104", accepts_marketplace_tickets=True)
        empty.services_offered.add(self.category)
        response = self.client.get(
            f"/api/v1/sync-ai/marketplace/availability/?category_id={self.category.id}&zip_code=36104"
        )
        ids = {row["business_id"] for row in response.data["results"]}
        self.assertIn(self.business.id, ids)
        self.assertNotIn(empty.id, ids)
