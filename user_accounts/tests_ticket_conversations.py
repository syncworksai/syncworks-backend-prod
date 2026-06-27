from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import Business, BusinessMember, ServiceCategory, Ticket, TicketMessage
from user_accounts.viewsets.ticket_conversations import (
    TicketConversationListAPIView,
    TicketConversationMessagesAPIView,
)


class TicketConversationScopeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="thread-customer",
            email="thread-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="thread-owner",
            email="thread-owner@example.com",
            password="test-pass-123",
        )
        self.tech = User.objects.create_user(
            username="thread-tech",
            email="thread-tech@example.com",
            password="test-pass-123",
        )
        self.other_tech = User.objects.create_user(
            username="thread-other-tech",
            email="thread-other-tech@example.com",
            password="test-pass-123",
        )

        self.business = Business.objects.create(
            owner=self.owner,
            name="Scoped Thread Company",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.tech,
            role="TECHNICIAN",
            is_active=True,
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.other_tech,
            role="TECHNICIAN",
            is_active=True,
        )
        self.category = ServiceCategory.objects.create(
            key="scoped-thread-service",
            name="Scoped Thread Service",
        )

        self.assigned_ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.tech,
            category=self.category,
            service_zip="36104",
        )
        self.other_ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.other_tech,
            category=self.category,
            service_zip="36104",
        )
        TicketMessage.objects.create(
            ticket=self.assigned_ticket,
            sender=self.customer,
            body="Initial customer message",
        )

        self.factory = APIRequestFactory()
        self.list_view = TicketConversationListAPIView.as_view()
        self.messages_view = TicketConversationMessagesAPIView.as_view()

    def list_call(self, user, scope, business_header=False):
        kwargs = {}
        if business_header:
            kwargs["HTTP_X_BUSINESS_ID"] = str(self.business.id)
        request = self.factory.get(
            f"/api/v1/ticket-conversations/?scope={scope}",
            **kwargs,
        )
        force_authenticate(request, user=user)
        return self.list_view(request)

    def test_personal_scope_only_returns_customer_tickets(self):
        response = self.list_call(self.customer, "PERSONAL")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["scope"], "PERSONAL")

    def test_owner_business_scope_sees_all_business_tickets(self):
        response = self.list_call(self.owner, "BUSINESS", business_header=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_technician_only_sees_assigned_ticket(self):
        response = self.list_call(self.tech, "BUSINESS", business_header=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.assigned_ticket.id)

    def test_ticket_message_posts_inside_visible_scope(self):
        request = self.factory.post(
            f"/api/v1/ticket-conversations/{self.assigned_ticket.id}/messages/?scope=BUSINESS",
            {"body": "Technician response"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = self.messages_view(request, ticket_id=self.assigned_ticket.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            TicketMessage.objects.filter(ticket=self.assigned_ticket).count(),
            2,
        )

    def test_technician_cannot_open_another_technicians_thread(self):
        request = self.factory.get(
            f"/api/v1/ticket-conversations/{self.other_ticket.id}/messages/?scope=BUSINESS",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = self.messages_view(request, ticket_id=self.other_ticket.id)
        self.assertEqual(response.status_code, 404)
