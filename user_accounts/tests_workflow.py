from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    Business,
    BusinessMember,
    ServiceCategory,
    Ticket,
    TicketDependency,
    TicketRequirement,
)
from user_accounts.viewsets.workflow import (
    BusinessPriorityQueueAPIView,
    TicketDependencyListCreateAPIView,
    TicketNextActionAPIView,
    TicketRequirementDetailAPIView,
    TicketRequirementListCreateAPIView,
)


class WorkflowDependencyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="workflow-customer",
            email="workflow-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="workflow-owner",
            email="workflow-owner@example.com",
            password="test-pass-123",
        )
        self.employee = User.objects.create_user(
            username="workflow-employee",
            email="workflow-employee@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Workflow Operations Co",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.employee,
            role="MANAGER",
            is_active=True,
        )
        self.category = ServiceCategory.objects.create(
            key="workflow-service",
            name="Workflow Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
            status="IN_PROGRESS",
        )
        self.factory = APIRequestFactory()

    def _auth(self, request):
        force_authenticate(request, user=self.employee)
        return request

    def test_blocking_requirement_controls_next_action(self):
        create = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/requirements/",
            {
                "requirement_type": "PART",
                "title": "Order replacement compressor",
                "description": "Work cannot continue until the part arrives.",
                "severity": "HIGH",
                "blocks_progress": True,
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketRequirementListCreateAPIView.as_view()(
            self._auth(create),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 201)

        request = self.factory.get(
            f"/api/v1/tickets/{self.ticket.id}/next-action/",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        next_action = TicketNextActionAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(next_action.status_code, 200)
        self.assertTrue(next_action.data["next_action"]["blocked"])
        self.assertEqual(
            next_action.data["next_action"]["action_code"],
            "RESOLVE_PART",
        )

    def test_satisfying_requirement_unblocks_ticket(self):
        requirement = TicketRequirement.objects.create(
            ticket=self.ticket,
            requirement_type="CUSTOMER_APPROVAL",
            title="Customer approval",
            blocks_progress=True,
        )
        request = self.factory.patch(
            f"/api/v1/requirements/{requirement.id}/",
            {"status": "SATISFIED"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketRequirementDetailAPIView.as_view()(
            self._auth(request),
            requirement_id=requirement.id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["satisfied_at"])

        next_request = self.factory.get(
            f"/api/v1/tickets/{self.ticket.id}/next-action/",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        next_response = TicketNextActionAPIView.as_view()(
            self._auth(next_request),
            ticket_id=self.ticket.id,
        )
        self.assertFalse(next_response.data["next_action"]["blocked"])
        self.assertEqual(
            next_response.data["next_action"]["action_code"],
            "CONTINUE_WORK",
        )

    def test_ticket_dependency_blocks_until_parent_is_completed(self):
        parent = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
            status="IN_PROGRESS",
        )
        request = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/dependencies/",
            {
                "depends_on_ticket": parent.id,
                "description": "Inspection must finish first.",
                "is_blocking": True,
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketDependencyListCreateAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 201)

        next_request = self.factory.get(
            f"/api/v1/tickets/{self.ticket.id}/next-action/",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        blocked = TicketNextActionAPIView.as_view()(
            self._auth(next_request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(
            blocked.data["next_action"]["action_code"],
            "WAIT_FOR_TICKET",
        )

        parent.status = "COMPLETED"
        parent.save(update_fields=["status"])

        unblocked = TicketNextActionAPIView.as_view()(
            self._auth(next_request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(
            unblocked.data["next_action"]["action_code"],
            "CONTINUE_WORK",
        )

    def test_priority_queue_promotes_overdue_critical_blocker(self):
        older = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
            status="ASSIGNED",
        )
        urgent = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
            status="IN_PROGRESS",
        )
        TicketRequirement.objects.create(
            ticket=urgent,
            requirement_type="CUSTOMER_RESPONSE",
            title="Emergency access confirmation",
            severity="CRITICAL",
            blocks_progress=True,
            due_at=timezone.now() - timedelta(hours=1),
        )

        request = self.factory.get(
            "/api/v1/workflow/priority-queue/",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = BusinessPriorityQueueAPIView.as_view()(
            self._auth(request)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["ticket_id"], urgent.id)

    def test_terminal_ticket_has_no_next_action(self):
        self.ticket.status = "CLOSED"
        self.ticket.save(update_fields=["status"])
        request = self.factory.get(
            f"/api/v1/tickets/{self.ticket.id}/next-action/",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketNextActionAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.data["next_action"]["state"], "DONE")
