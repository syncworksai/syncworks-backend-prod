from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from user_accounts.models import Business, ServiceCategory, ServiceRequest, Ticket
from user_accounts.services.tickets import is_ticket_eligible_for_business


class ExpandedServiceAreaMatchingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="coverage-owner",
            email="coverage-owner@example.com",
            password="test-pass-123",
        )
        self.customer = User.objects.create_user(
            username="coverage-customer",
            email="coverage-customer@example.com",
            password="test-pass-123",
        )
        self.category = ServiceCategory.objects.create(
            name="Coverage Test Service",
            key="coverage-test-service",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Coverage Test Business",
            base_zip="36104",
            service_radius_miles=25,
            accepts_marketplace_tickets=True,
        )
        self.business.services_offered.add(self.category)

    def make_ticket(self, zip_code="99999", intake=None, cents=0):
        request = ServiceRequest.objects.create(
            customer=self.customer,
            category=self.category,
            title="Coverage test",
            zip_code=zip_code,
            intake_payload=intake or {},
        )
        return Ticket.objects.create(
            service_request=request,
            customer=self.customer,
            category=self.category,
            is_marketplace=True,
            service_zip=zip_code,
            total_amount_cents=cents,
        )

    def test_existing_exact_zip_still_matches(self):
        ticket = self.make_ticket(zip_code="36104")
        self.assertTrue(is_ticket_eligible_for_business(ticket, self.business))

    @patch(
        "user_accounts.services.tickets._zip_geo_parts",
        return_value={"zip": "90210", "city": "BEVERLY HILLS", "county": "LOS ANGELES", "state": "CA"},
    )
    def test_exact_expanded_zip_matches(self, _geo):
        self.business.service_areas = [
            {"area_type": "ZIP", "values": ["90210"], "project_scope": "BOTH", "active": True}
        ]
        self.business.save(update_fields=["service_areas"])
        ticket = self.make_ticket(zip_code="90210")
        self.assertTrue(is_ticket_eligible_for_business(ticket, self.business))

    @patch(
        "user_accounts.services.tickets._zip_geo_parts",
        return_value={"zip": "33101", "city": "MIAMI", "county": "MIAMI-DADE", "state": "FL"},
    )
    def test_state_rule_matches(self, _geo):
        self.business.service_areas = [
            {"area_type": "STATE", "values": ["FL"], "project_scope": "BOTH", "active": True}
        ]
        self.business.save(update_fields=["service_areas"])
        ticket = self.make_ticket(zip_code="33101")
        self.assertTrue(is_ticket_eligible_for_business(ticket, self.business))

    @patch(
        "user_accounts.services.tickets._zip_geo_parts",
        return_value={"zip": "10001", "city": "NEW YORK", "county": "NEW YORK", "state": "NY"},
    )
    def test_nationwide_rule_matches(self, _geo):
        self.business.service_areas = [
            {"area_type": "NATIONWIDE", "values": ["US"], "project_scope": "BOTH", "active": True}
        ]
        self.business.save(update_fields=["service_areas"])
        ticket = self.make_ticket(zip_code="10001")
        self.assertTrue(is_ticket_eligible_for_business(ticket, self.business))

    @patch(
        "user_accounts.services.tickets._zip_geo_parts",
        return_value={"zip": "10001", "city": "NEW YORK", "county": "NEW YORK", "state": "NY"},
    )
    def test_inactive_rule_does_not_match(self, _geo):
        self.business.service_areas = [
            {"area_type": "NATIONWIDE", "values": ["US"], "project_scope": "BOTH", "active": False}
        ]
        self.business.save(update_fields=["service_areas"])
        ticket = self.make_ticket(zip_code="10001")
        self.assertFalse(is_ticket_eligible_for_business(ticket, self.business))

    @patch(
        "user_accounts.services.tickets._zip_geo_parts",
        return_value={"zip": "10001", "city": "NEW YORK", "county": "NEW YORK", "state": "NY"},
    )
    def test_restricted_rule_requires_intake_data(self, _geo):
        self.business.service_areas = [
            {
                "area_type": "NATIONWIDE",
                "values": ["US"],
                "project_scope": "COMMERCIAL",
                "minimum_project_amount": "25000",
                "active": True,
            }
        ]
        self.business.save(update_fields=["service_areas"])

        unknown = self.make_ticket(zip_code="10001")
        self.assertFalse(is_ticket_eligible_for_business(unknown, self.business))

        qualifying = self.make_ticket(
            zip_code="10001",
            intake={"project_scope": "commercial", "estimated_budget": 30000},
        )
        self.assertTrue(is_ticket_eligible_for_business(qualifying, self.business))
