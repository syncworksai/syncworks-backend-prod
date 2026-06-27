from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    Business,
    BusinessMember,
    ServiceCategory,
    Ticket,
    TicketConversationReadState,
    TicketMessage,
)
from user_accounts.viewsets.ticket_conversations import (
    TicketConversationControlsAPIView,
    TicketConversationListAPIView,
    TicketConversationMessagesAPIView,
)


class TicketConversationReadStateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username="read-customer", email="read-customer@example.com", password="test-pass-123")
        self.owner = User.objects.create_user(username="read-owner", email="read-owner@example.com", password="test-pass-123")
        self.tech = User.objects.create_user(username="read-tech", email="read-tech@example.com", password="test-pass-123")
        self.business = Business.objects.create(owner=self.owner, name="Read State Company")
        BusinessMember.objects.create(business=self.business, user=self.tech, role="TECHNICIAN", is_active=True)
        self.category = ServiceCategory.objects.create(key="read-state-service", name="Read State Service")
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.tech,
            category=self.category,
        )
        self.message = TicketMessage.objects.create(
            ticket=self.ticket,
            sender=self.customer,
            body="Unread customer message",
        )
        self.factory = APIRequestFactory()

    def test_business_thread_starts_unread_for_technician(self):
        request = self.factory.get(
            "/api/v1/ticket-conversations/?scope=BUSINESS",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = TicketConversationListAPIView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_total"], 1)
        self.assertEqual(response.data["results"][0]["unread_count"], 1)

    def test_opening_thread_marks_visible_messages_read(self):
        request = self.factory.get(
            f"/api/v1/ticket-conversations/{self.ticket.id}/messages/?scope=BUSINESS",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = TicketConversationMessagesAPIView.as_view()(request, ticket_id=self.ticket.id)
        self.assertEqual(response.status_code, 200)
        state = TicketConversationReadState.objects.get(user=self.tech, ticket=self.ticket, scope="BUSINESS")
        self.assertEqual(state.last_read_message_id, self.message.id)

    def test_customer_read_state_is_independent(self):
        request = self.factory.get(
            f"/api/v1/ticket-conversations/{self.ticket.id}/messages/?scope=BUSINESS",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        TicketConversationMessagesAPIView.as_view()(request, ticket_id=self.ticket.id)

        personal = self.factory.get("/api/v1/ticket-conversations/?scope=PERSONAL")
        force_authenticate(personal, user=self.customer)
        response = TicketConversationListAPIView.as_view()(personal)
        self.assertEqual(response.data["unread_total"], 0)
        self.assertFalse(TicketConversationReadState.objects.filter(
            user=self.customer, ticket=self.ticket, scope="PERSONAL"
        ).exists())

    def test_new_message_after_read_becomes_unread(self):
        TicketConversationReadState.objects.create(
            user=self.tech,
            ticket=self.ticket,
            scope="BUSINESS",
            last_read_message=self.message,
        )
        TicketMessage.objects.create(
            ticket=self.ticket,
            sender=self.customer,
            body="A newer customer message",
        )
        request = self.factory.get(
            "/api/v1/ticket-conversations/?scope=BUSINESS",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = TicketConversationListAPIView.as_view()(request)
        self.assertEqual(response.data["results"][0]["unread_count"], 1)

    def test_user_can_pin_and_mute_visible_thread(self):
        request = self.factory.patch(
            f"/api/v1/ticket-conversations/{self.ticket.id}/controls/?scope=BUSINESS",
            {"pinned": True, "muted": True},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = TicketConversationControlsAPIView.as_view()(
            request,
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["controls"]["pinned"])
        self.assertTrue(response.data["controls"]["muted"])

    def test_attention_reason_is_user_specific(self):
        request = self.factory.patch(
            f"/api/v1/ticket-conversations/{self.ticket.id}/controls/?scope=BUSINESS",
            {
                "needs_attention": True,
                "attention_reason": "Customer needs a callback",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.tech)
        response = TicketConversationControlsAPIView.as_view()(
            request,
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["controls"]["needs_attention"])
        self.assertEqual(
            response.data["controls"]["attention_reason"],
            "Customer needs a callback",
        )
        self.assertFalse(
            TicketConversationReadState.objects.filter(
                user=self.owner,
                ticket=self.ticket,
                scope="BUSINESS",
            ).exists()
        )

    def test_controls_reject_ticket_outside_user_scope(self):
        other = get_user_model().objects.create_user(
            username="other-user",
            email="other-user@example.com",
            password="test-pass-123",
        )
        request = self.factory.patch(
            f"/api/v1/ticket-conversations/{self.ticket.id}/controls/?scope=PERSONAL",
            {"pinned": True},
            format="json",
        )
        force_authenticate(request, user=other)
        response = TicketConversationControlsAPIView.as_view()(
            request,
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 404)
