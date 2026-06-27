from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from user_accounts.models import ServiceCategory, ServiceRequest, Ticket
from user_accounts.serializers.tickets import TicketSerializer


class TicketOpportunityProfileTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="opportunity-profile-customer",
            email="opportunity-profile@example.com",
            password="test-pass-123",
        )
        self.category = ServiceCategory.objects.create(
            name="Water Heater Installation",
            key="opportunity-water-heater",
        )

    def make_ticket(self):
        request = ServiceRequest.objects.create(
            customer=self.customer,
            category=self.category,
            title="Install a commercial water heater",
            description=(
                "Commercial project. Estimated budget: $4,500. "
                "Needed this week."
            ),
        )
        if hasattr(request, "priority"):
            request.priority = "P2"
        if hasattr(request, "needed_by_date"):
            request.needed_by_date = "2026-07-03"
        if hasattr(request, "preferred_time_window"):
            request.preferred_time_window = "Morning"
        if hasattr(request, "intake_payload"):
            request.intake_payload = {
                "project_scope": "COMMERCIAL",
                "estimated_budget": 4500,
            }
        request.save()

        return Ticket.objects.create(
            service_request=request,
            customer=self.customer,
            category=self.category,
            is_marketplace=True,
            service_zip="36104",
        )

    def test_serializer_exposes_normalized_opportunity_profile(self):
        ticket = self.make_ticket()
        request = APIRequestFactory().get("/api/v1/tickets/marketplace/")
        request.user = self.customer

        data = TicketSerializer(ticket, context={"request": request}).data
        profile = data["opportunity_profile"]

        self.assertEqual(profile["category_key"], self.category.key)
        self.assertEqual(profile["category_name"], self.category.name)
        self.assertEqual(profile["project_scope"], "COMMERCIAL")
        self.assertEqual(profile["estimated_value"], 4500)
        self.assertTrue(profile["has_known_value"])
