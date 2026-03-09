from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token
from user_accounts.models import User, Roles, Notification


class TestNotifications(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="n@test.com",
            password="Password123!",
            role=Roles.CUSTOMER,
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_unread_count(self):
        Notification.objects.create(user=self.user, title="Hi", body="")
        r = self.client.get("/api/v1/notifications/unread-count/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["unread"], 1)
