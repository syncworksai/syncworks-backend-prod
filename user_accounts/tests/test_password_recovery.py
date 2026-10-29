from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

User = get_user_model()

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_URL="https://syncworksapp.com",
    PASSWORD_RESET_TIMEOUT=3600,
)
class PasswordRecoveryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pilot-owner",
            email="pilot@example.com",
            password="ExistingStrongPwd123!",
        )

    def test_request_non_enumeration_and_valid_reset(self):
        missing = self.client.post("/api/v1/auth/password/reset/request/", {"email": "missing@example.com"}, format="json")
        existent = self.client.post("/api/v1/auth/password/reset/request/", {"email": "pilot@example.com"}, format="json")
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.data, existent.data)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        url = next(piece for piece in body.split() if piece.startswith("https://syncworksapp.com/reset-password?"))
        params = parse_qs(urlsplit(url).query)
        token = Token.objects.create(user=self.user)
        confirm = {
            "uid": params["uid"][0], "token": params["token"][0], "new_password": "ChangedStrongPwd456!",
        }
        result = self.client.post("/api/v1/auth/password/reset/confirm/", confirm, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(confirm["new_password"]))
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
        self.assertEqual(self.client.post("/api/v1/auth/password/reset/confirm/", confirm, format="json").status_code, 400)

    def test_invalid_token_and_weak_password_fail(self):
        bad = self.client.post("/api/v1/auth/password/reset/confirm/", {
            "uid": "not-a-user", "token": "invalid", "new_password": "new"
        }, format="json")
        self.assertEqual(bad.status_code, 400)
        self.client.post("/api/v1/auth/password/reset/request/", {"email": "pilot@example.com"}, format="json")
        url = next(piece for piece in mail.outbox[-1].body.split() if "/reset-password?" in piece)
        params = parse_qs(urlsplit(url).query)
        result = self.client.post("/api/v1/auth/password/reset/confirm/", {
            "uid": params["uid"][0], "token": params["token"][0], "new_password": "123"
        }, format="json")
        self.assertEqual(result.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ExistingStrongPwd123!"))

    def test_change_password_requires_current_and_revokes_session(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)
        bad = self.client.post("/api/v1/auth/change-password/", {
            "current_password": "bad", "new_password": "NewStrongPwd789!"
        }, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/v1/auth/change-password/", {
            "current_password": "ExistingStrongPwd123!", "new_password": "NewStrongPwd789!"
        }, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPwd789!"))
