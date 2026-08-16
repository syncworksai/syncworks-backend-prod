from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from sync_ai.context import resolve_workspace
from user_accounts.models import AuditLog, Business, FinanceAccount, FinanceBudget, FinanceLiability, FinanceObligation, ServiceRequest, Ticket, TicketMessage


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class SyncAITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sync-test", email="sync-test@example.com", password="test-password-123")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def provider_response(self, text="Prepared draft"):
        provider = Mock()
        provider.status_code = 200
        provider.json.return_value = {"id": "resp_test", "model": "gpt-5-mini", "output_text": text, "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}}
        return provider

    def make_ticket(self, **kwargs):
        request = ServiceRequest.objects.create(customer=kwargs.pop("customer", self.user), title="Repair kitchen sink", status="NEW")
        return Ticket.objects.create(customer=request.customer, service_request=request, work_title="Kitchen sink repair", status=kwargs.pop("status", "SCHEDULED"), **kwargs)

    def test_status_does_not_expose_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.get("/api/v1/sync-ai/status/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        self.assertTrue(response.data["capabilities"]["execution"]["ticket_reply"])
        self.assertFalse(response.data["capabilities"]["execution"]["schedule_change"])
        self.assertNotIn("secret-test-key", str(response.data))

    @patch("sync_ai.service.requests.post")
    def test_personal_chat(self, post):
        post.return_value = self.provider_response("Your next appointment is ready to review.")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.post("/api/v1/sync-ai/chat/", {"workspace": "personal", "message": "What is next?"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["workspace"], "personal")

    @patch("sync_ai.service.requests.post")
    def test_prepare_ticket_reply_never_executes(self, post):
        post.return_value = self.provider_response("Thanks for the update. We will review the next available time.")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.post("/api/v1/sync-ai/actions/prepare/", {"workspace": "personal", "action_type": "ticket_reply", "instruction": "Thank them and say we will review scheduling."}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["executed"])
        self.assertEqual(TicketMessage.objects.count(), 0)

    @patch("sync_ai.service.requests.post")
    def test_lead_follow_up_requires_business_workspace(self, post):
        response = self.client.post("/api/v1/sync-ai/actions/prepare/", {"workspace": "personal", "action_type": "lead_follow_up", "instruction": "Follow up with this lead."}, format="json")
        self.assertEqual(response.status_code, 403)
        post.assert_not_called()

    def test_personal_ticket_reply_requires_confirmation(self):
        ticket = self.make_ticket()
        response = self.client.post("/api/v1/sync-ai/actions/ticket-reply/execute/", {"workspace": "personal", "ticket_id": ticket.id, "body": "Confirmed reply.", "confirmed": False}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(TicketMessage.objects.count(), 0)

    def test_personal_ticket_reply_executes_and_audits(self):
        ticket = self.make_ticket()
        response = self.client.post("/api/v1/sync-ai/actions/ticket-reply/execute/", {"workspace": "personal", "ticket_id": ticket.id, "body": "Confirmed reply.", "confirmed": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["executed"])
        self.assertEqual(TicketMessage.objects.get(ticket=ticket).sender_id, self.user.id)
        self.assertTrue(AuditLog.objects.filter(actor=self.user, action="sync_ai.ticket_reply_executed").exists())

    def test_personal_cannot_reply_to_another_users_ticket(self):
        other = get_user_model().objects.create_user(username="other-user", email="other@example.com", password="password-123")
        ticket = self.make_ticket(customer=other)
        response = self.client.post("/api/v1/sync-ai/actions/ticket-reply/execute/", {"workspace": "personal", "ticket_id": ticket.id, "body": "Should fail.", "confirmed": True}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TicketMessage.objects.count(), 0)

    def test_business_reply_is_scoped_to_active_business(self):
        business = Business.objects.create(owner=self.user, name="SYNC Test Services")
        ticket = self.make_ticket(assigned_business=business)
        response = self.client.post("/api/v1/sync-ai/actions/ticket-reply/execute/", {"workspace": "business", "ticket_id": ticket.id, "body": "Business reply.", "confirmed": True}, format="json", HTTP_X_BUSINESS_ID=str(business.id))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["ticket_id"], ticket.id)

    def test_personal_snapshot_uses_existing_requests_and_tickets(self):
        self.make_ticket()
        context = resolve_workspace(user=self.user, workspace="personal", business_id=None)
        self.assertEqual(context.data["service_requests"]["active"], 1)
        self.assertEqual(context.data["tickets"]["active"], 1)

    def test_personal_snapshot_exposes_finance_decisions_not_raw_transactions(self):
        FinanceAccount.objects.create(user=self.user, name="Checking", kind="CHECKING", current_balance=Decimal("2500.00"), is_manual=True)
        FinanceObligation.objects.create(user=self.user, name="Mortgage", category="HOUSING", expected_amount=Decimal("1000.00"), next_due_date=__import__("django").utils.timezone.localdate(), recurring=True, active=True, is_manual=True)
        FinanceLiability.objects.create(user=self.user, name="Visa", kind="CREDIT_CARD", outstanding_balance=Decimal("3000.00"), minimum_payment=Decimal("90.00"), apr=Decimal("24.99"), is_manual=True)
        FinanceBudget.objects.create(user=self.user, name="Dining", category="DINING", monthly_limit=Decimal("300.00"))
        context = resolve_workspace(user=self.user, workspace="personal", business_id=None)
        finance = context.data["finance"]
        self.assertTrue(finance["available"])
        self.assertEqual(finance["safe_to_spend_now"], 1500.0)
        self.assertEqual(finance["debt_strategy"]["top_target"]["name"], "Visa")
        self.assertEqual(finance["active_budget_count"], 1)
        self.assertNotIn("transactions", finance)

    def test_business_snapshot_is_scoped_to_active_business(self):
        business = Business.objects.create(owner=self.user, name="SYNC Test Services")
        self.make_ticket(assigned_business=business, status="IN_PROGRESS", total_amount_cents=12500)
        context = resolve_workspace(user=self.user, workspace="business", business_id=str(business.id))
        self.assertEqual(context.data["operations"]["active_jobs"], 1)
