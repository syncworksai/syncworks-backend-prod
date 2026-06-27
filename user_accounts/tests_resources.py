from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    Business,
    BusinessMember,
    BusinessResource,
    ResourceAssignment,
    ServiceCategory,
    Ticket,
    TrackableAsset,
)
from user_accounts.viewsets.resources import (
    ResourceAssignmentDetailAPIView,
    ResourceListCreateAPIView,
    ResourceMovementAPIView,
    TicketResourceAssignmentAPIView,
)


class UniversalResourceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="resource-customer",
            email="resource-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="resource-owner",
            email="resource-owner@example.com",
            password="test-pass-123",
        )
        self.employee = User.objects.create_user(
            username="resource-employee",
            email="resource-employee@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Resource Operations Co",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.employee,
            role="TECHNICIAN",
            is_active=True,
        )
        self.category = ServiceCategory.objects.create(
            key="resource-service",
            name="Resource Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
        )
        self.factory = APIRequestFactory()

    def _auth(self, request):
        force_authenticate(request, user=self.employee)
        return request

    def test_create_universal_resource(self):
        request = self.factory.post(
            "/api/v1/resources/",
            {
                "name": "Bay 1",
                "resource_type": "BAY",
                "location": "Main Shop",
                "capacity": 1,
                "skills": ["ALIGNMENT", "BRAKES"],
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = ResourceListCreateAPIView.as_view()(self._auth(request))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["resource_type"], "BAY")
        self.assertEqual(response.data["available_capacity"], 1)

    def test_resource_capacity_blocks_extra_assignment(self):
        resource = BusinessResource.objects.create(
            business=self.business,
            name="Station 1",
            resource_type="STATION",
            capacity=1,
        )
        request = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/resources/",
            {"resource": resource.id, "status": "ACTIVE"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketResourceAssignmentAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 201)

        second_ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
        )
        second = self.factory.post(
            f"/api/v1/tickets/{second_ticket.id}/resources/",
            {"resource": resource.id, "status": "ACTIVE"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        blocked = TicketResourceAssignmentAPIView.as_view()(
            self._auth(second),
            ticket_id=second_ticket.id,
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("capacity", str(blocked.data).lower())

    def test_completing_assignment_releases_resource(self):
        resource = BusinessResource.objects.create(
            business=self.business,
            name="Crew A",
            resource_type="CREW",
            capacity=1,
            status="OCCUPIED",
        )
        assignment = ResourceAssignment.objects.create(
            resource=resource,
            ticket=self.ticket,
            status="ACTIVE",
        )
        request = self.factory.patch(
            f"/api/v1/resource-assignments/{assignment.id}/",
            {"status": "COMPLETED"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = ResourceAssignmentDetailAPIView.as_view()(
            self._auth(request),
            assignment_id=assignment.id,
        )
        self.assertEqual(response.status_code, 200)
        resource.refresh_from_db()
        self.assertEqual(resource.status, "AVAILABLE")

    def test_move_asset_and_resource_location(self):
        resource = BusinessResource.objects.create(
            business=self.business,
            name="Holding Area A",
            resource_type="HOLDING_AREA",
            location="Receiving",
        )
        asset = TrackableAsset.objects.create(
            business=self.business,
            customer=self.customer,
            asset_type="EQUIPMENT",
            name="Customer Equipment",
        )
        request = self.factory.post(
            f"/api/v1/resources/{resource.id}/movements/",
            {
                "asset": asset.id,
                "ticket": self.ticket.id,
                "to_location": "Ready Queue",
                "reason": "Inspection complete",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = ResourceMovementAPIView.as_view()(
            self._auth(request),
            resource_id=resource.id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["from_location"], "Receiving")
        resource.refresh_from_db()
        self.assertEqual(resource.location, "Ready Queue")

    def test_unavailable_resource_cannot_be_assigned(self):
        resource = BusinessResource.objects.create(
            business=self.business,
            name="Machine 1",
            resource_type="MACHINE",
            status="MAINTENANCE",
        )
        request = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/resources/",
            {"resource": resource.id, "status": "ACTIVE"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketResourceAssignmentAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("assignable", str(response.data).lower())
