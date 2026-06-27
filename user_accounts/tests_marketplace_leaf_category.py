from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import ServiceCategory
from user_accounts.viewsets.marketplace import ServiceRequestViewSet


class MarketplaceLeafCategoryValidationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="leaf-category-customer",
            email="leaf-category-customer@example.com",
            password="test-pass-123",
        )
        self.parent = ServiceCategory.objects.create(
            name="Plumbing",
            key="leaf-validation-plumbing",
        )
        self.leaf = ServiceCategory.objects.create(
            name="Water Heater Installation",
            key="leaf-validation-water-heater",
            parent=self.parent,
        )
        self.factory = APIRequestFactory()
        self.view = ServiceRequestViewSet.as_view({"post": "create"})

    def request(self, category_id, marketplace=True):
        request = self.factory.post(
            "/api/v1/service-requests/",
            {
                "category": category_id,
                "title": "Water heater help",
                "description": "Replace the existing unit.",
                "service_address": "100 Main St, Montgomery, AL 36104",
                "service_zip": "36104",
                "service_radius_miles": 25,
                "is_marketplace": marketplace,
            },
            format="json",
        )
        force_authenticate(request, user=self.user)
        return self.view(request)

    def test_marketplace_rejects_broad_parent_category(self):
        response = self.request(self.parent.id, marketplace=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("category", response.data)

    def test_marketplace_accepts_leaf_category(self):
        response = self.request(self.leaf.id, marketplace=True)
        self.assertEqual(response.status_code, 201)
