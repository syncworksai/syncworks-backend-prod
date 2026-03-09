from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from user_accounts.models import User, Roles, ServiceCategory
from user_accounts.services.tickets import create_request_and_ticket


class TestMessagePermissions(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email="cust@test.com",
            password="Password123!",
            role=Roles.CUSTOMER,
        )
        self.token = Token.objects.create(user=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.cat = ServiceCategory.objects.create(key="plumbing", name="Plumbing", description="")
        sr = create_request_and_ticket(self.customer, self.cat, "Fix", "Leak")
        self.ticket = sr.ticket

    def test_customer_cannot_post_internal(self):
        r = self.client.post(
            "/api/v1/ticket-messages/",
            {"ticket": self.ticket.id, "body": "internal", "type": "INTERNAL"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)
