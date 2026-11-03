from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from user_accounts.models import Business, ServiceCategory, Ticket
from user_accounts.services.tickets import ticket_eligible_businesses, marketplace_tickets_for_business


class BusinessMarketplaceAcceptanceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="beta-owner", email="owner-beta@example.test", password="testStrongPass123!")
        self.customer = User.objects.create_user(username="beta-customer", email="customer-beta@example.test", password="testStrongPass123!")
        self.outsider = User.objects.create_user(username="beta-outsider", email="outsider-beta@example.test", password="testStrongPass123!")
        self.category = ServiceCategory.objects.create(name="Beta Notary", key="beta-notary", is_active=True)
        self.other = ServiceCategory.objects.create(name="Beta Plumbing", key="beta-plumbing", is_active=True)
        self.alabama = Business.objects.create(owner=self.owner, name="Alabama Beta Notary", is_active=True, accepts_marketplace_tickets=True, base_zip="36117", state="AL", service_radius_miles=25)
        self.florida = Business.objects.create(owner=self.owner, name="Florida Beta Notary", is_active=True, accepts_marketplace_tickets=True, base_zip="33101", state="FL", service_radius_miles=25)
        self.wrong_service = Business.objects.create(owner=self.owner, name="Alabama Beta Plumber", is_active=True, accepts_marketplace_tickets=True, base_zip="36117", state="AL", service_radius_miles=25)
        self.alabama.services_offered.add(self.category)
        self.florida.services_offered.add(self.category)
        self.wrong_service.services_offered.add(self.other)

    def test_business_lookup_requires_membership(self):
        client = APIClient()
        client.force_authenticate(self.outsider)
        response = client.get(f"/api/v1/businesses/{self.alabama.id}/")
        self.assertIn(response.status_code, [403, 404])
        client.force_authenticate(self.owner)
        response = client.get(f"/api/v1/businesses/{self.alabama.id}/")
        self.assertEqual(response.status_code, 200)

    def test_category_directory_is_available_to_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(self.customer)
        response = client.get("/api/v1/service-categories/")
        self.assertEqual(response.status_code, 200)
        items = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        ids = [item["id"] for item in items]
        self.assertIn(self.category.id, ids)

    def test_marketplace_ticket_is_only_eligible_for_correct_area_and_category(self):
        ticket = Ticket.objects.create(customer=self.customer, category=self.category, service_zip="36117", is_marketplace=True, status=Ticket.Status.NEW)
        eligible = set(ticket_eligible_businesses(ticket).values_list("id", flat=True))
        self.assertIn(self.alabama.id, eligible)
        self.assertNotIn(self.florida.id, eligible)
        self.assertNotIn(self.wrong_service.id, eligible)
        visible = set(marketplace_tickets_for_business(self.alabama).values_list("id", flat=True))
        self.assertIn(ticket.id, visible)
        invisible = set(marketplace_tickets_for_business(self.florida).values_list("id", flat=True))
        self.assertNotIn(ticket.id, invisible)
