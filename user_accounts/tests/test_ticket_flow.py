from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token
from user_accounts.models import User, ServiceCategory
from user_accounts.models.roles import Roles


class TestTicketFlow(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="c@test.com",
            email="c@test.com",
            password="Password123!",
            role=Roles.CUSTOMER,
        )
        self.token = Token.objects.create(user=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.cat = ServiceCategory.objects.create(key="plumbing", name="Plumbing")

    def test_create_request_creates_ticket(self):
        r = self.client.post(
            "/api/v1/service-requests/",
            {"category": self.cat.id, "title": "Fix faucet", "description": "Leak"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertIn("ticket_id", r.data)

        r2 = self.client.get("/api/v1/tickets/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["count"], 1)
