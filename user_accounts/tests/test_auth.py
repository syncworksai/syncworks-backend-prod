from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


@override_settings(
    AUTH_VERIFICATION_BYPASS_EMAILS=[
        "auth-test@example.com",
    ]
)
class TestAuth(APITestCase):
    register_url = "/api/v1/auth/register/"
    login_url = "/api/v1/auth/login/"
    me_url = "/api/v1/auth/me/"
    logout_url = "/api/v1/auth/logout/"

    def test_register_and_login(self):
        register_payload = {
            "email": "auth-test@example.com",
            "username": "auth_test_user",
            "password": "StrongTestPassword123!",
            "confirm_password": "StrongTestPassword123!",
            "first_name": "Auth",
            "last_name": "Test",
            "affiliate_code": "",
            "promo_code": "",
            "registration_source": "WEB",
        }

        register_response = self.client.post(
            self.register_url,
            register_payload,
            format="json",
        )

        self.assertEqual(
            register_response.status_code,
            status.HTTP_201_CREATED,
            register_response.data,
        )

        self.assertIn("token", register_response.data)
        self.assertIn("user", register_response.data)

        registered_user = register_response.data["user"]

        self.assertEqual(
            registered_user["email"],
            "auth-test@example.com",
        )
        self.assertTrue(
            registered_user["email_verified"]
        )

        user = User.objects.get(
            email__iexact="auth-test@example.com"
        )

        self.assertTrue(user.email_verified)
        self.assertTrue(user.is_test_account)
        self.assertEqual(
            user.registration_source,
            "WEB",
        )

        login_payload = {
            "identifier": "auth-test@example.com",
            "password": "StrongTestPassword123!",
        }

        login_response = self.client.post(
            self.login_url,
            login_payload,
            format="json",
        )

        self.assertEqual(
            login_response.status_code,
            status.HTTP_200_OK,
            login_response.data,
        )

        self.assertIn("token", login_response.data)
        self.assertEqual(
            login_response.data["user_id"],
            user.id,
        )
        self.assertTrue(
            login_response.data["email_verified"]
        )

    def test_register_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="existing_auth_user",
            email="existing@example.com",
            password="StrongTestPassword123!",
            email_verified=True,
        )

        payload = {
            "email": "EXISTING@example.com",
            "username": "another_auth_user",
            "password": "StrongTestPassword123!",
            "confirm_password": "StrongTestPassword123!",
            "first_name": "Another",
            "last_name": "User",
            "registration_source": "WEB",
        }

        response = self.client.post(
            self.register_url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        self.assertIn("email", response.data)

    def test_register_rejects_mismatched_passwords(self):
        payload = {
            "email": "auth-test@example.com",
            "username": "password_mismatch_user",
            "password": "StrongTestPassword123!",
            "confirm_password": "DifferentPassword123!",
            "first_name": "Password",
            "last_name": "Mismatch",
            "registration_source": "WEB",
        }

        response = self.client.post(
            self.register_url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        self.assertIn(
            "confirm_password",
            response.data,
        )

    def test_authenticated_user_can_read_me(self):
        user = User.objects.create_user(
            username="me_test_user",
            email="me-test@example.com",
            password="StrongTestPassword123!",
            email_verified=True,
        )

        login_response = self.client.post(
            self.login_url,
            {
                "identifier": "me-test@example.com",
                "password": "StrongTestPassword123!",
            },
            format="json",
        )

        self.assertEqual(
            login_response.status_code,
            status.HTTP_200_OK,
            login_response.data,
        )

        token = login_response.data["token"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token}"
        )

        me_response = self.client.get(
            self.me_url
        )

        self.assertEqual(
            me_response.status_code,
            status.HTTP_200_OK,
            me_response.data,
        )

        self.assertEqual(
            me_response.data["id"],
            user.id,
        )
        self.assertEqual(
            me_response.data["email"],
            "me-test@example.com",
        )
        self.assertTrue(
            me_response.data["email_verified"]
        )

    def test_logout_removes_token(self):
        user = User.objects.create_user(
            username="logout_test_user",
            email="logout-test@example.com",
            password="StrongTestPassword123!",
            email_verified=True,
        )

        login_response = self.client.post(
            self.login_url,
            {
                "identifier": user.email,
                "password": "StrongTestPassword123!",
            },
            format="json",
        )

        self.assertEqual(
            login_response.status_code,
            status.HTTP_200_OK,
            login_response.data,
        )

        token = login_response.data["token"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token}"
        )

        logout_response = self.client.post(
            self.logout_url,
            {},
            format="json",
        )

        self.assertEqual(
            logout_response.status_code,
            status.HTTP_200_OK,
            logout_response.data,
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token}"
        )

        me_response = self.client.get(
            self.me_url
        )

        self.assertEqual(
            me_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )