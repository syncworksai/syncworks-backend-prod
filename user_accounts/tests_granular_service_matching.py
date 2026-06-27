from django.contrib.auth import get_user_model
from django.test import TestCase

from user_accounts.models import Business, ServiceCategory, ServiceRequest, Ticket
from user_accounts.services.tickets import is_ticket_eligible_for_business


class GranularServiceMatchingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="granular-owner",
            email="granular-owner@example.com",
            password="test-pass-123",
        )
        self.customer = User.objects.create_user(
            username="granular-customer",
            email="granular-customer@example.com",
            password="test-pass-123",
        )
        self.plumbing = ServiceCategory.objects.create(name="Plumbing", key="granular-plumbing")
        self.water_heaters = ServiceCategory.objects.create(
            name="Water Heater Installation",
            key="granular-water-heater-installation",
            parent=self.plumbing,
        )
        self.leaky_pipes = ServiceCategory.objects.create(
            name="Leaky Pipe Repair",
            key="granular-leaky-pipe-repair",
            parent=self.plumbing,
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Water Heater Specialists",
            base_zip="36104",
            service_radius_miles=25,
            accepts_marketplace_tickets=True,
        )

    def make_ticket(self, category):
        request = ServiceRequest.objects.create(
            customer=self.customer,
            category=category,
            title=category.name,
            zip_code="36104",
        )
        return Ticket.objects.create(
            service_request=request,
            customer=self.customer,
            category=category,
            is_marketplace=True,
            service_zip="36104",
        )

    def test_legacy_broad_group_matches_all_descendants(self):
        self.business.services_offered.set([self.plumbing])
        self.business.detailed_services_enabled = False
        self.business.save(update_fields=["detailed_services_enabled"])
        self.assertTrue(is_ticket_eligible_for_business(self.make_ticket(self.water_heaters), self.business))
        self.assertTrue(is_ticket_eligible_for_business(self.make_ticket(self.leaky_pipes), self.business))

    def test_detailed_mode_only_matches_selected_leaf(self):
        self.business.services_offered.set([self.water_heaters])
        self.business.detailed_services_enabled = True
        self.business.save(update_fields=["detailed_services_enabled"])
        self.assertTrue(is_ticket_eligible_for_business(self.make_ticket(self.water_heaters), self.business))
        self.assertFalse(is_ticket_eligible_for_business(self.make_ticket(self.leaky_pipes), self.business))

    def test_detailed_mode_does_not_expand_parent(self):
        self.business.services_offered.set([self.plumbing])
        self.business.detailed_services_enabled = True
        self.business.save(update_fields=["detailed_services_enabled"])
        self.assertFalse(is_ticket_eligible_for_business(self.make_ticket(self.water_heaters), self.business))
