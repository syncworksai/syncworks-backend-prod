from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class ProductionReadinessTests(APITestCase):
    endpoint = "/api/v1/sync-ai/production/readiness/"

    def setUp(self):
        User = get_user_model()
        self.god = User.objects.create_user(
            username="production-god",
            email="production-god@example.com",
            password="test-password-123",
        )
        self.regular = User.objects.create_user(
            username="production-regular",
            email="production-regular@example.com",
            password="test-password-123",
        )
        self.god_token = Token.objects.create(user=self.god)
        self.regular_token = Token.objects.create(user=self.regular)

    @override_settings(GOD_MODE_EMAIL_ALLOWLIST=["production-god@example.com"])
    def test_non_god_mode_is_denied(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.regular_token.key}")
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 403)

    @override_settings(
        GOD_MODE_EMAIL_ALLOWLIST=["production-god@example.com"],
        DEBUG=False,
        SECRET_KEY="test-production-secret-not-default",
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_HSTS_SECONDS=3600,
        ALLOWED_HOSTS=["syncworks-api.onrender.com"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.com",
        DEFAULT_FROM_EMAIL="SyncWorks <no-reply@syncworksapp.com>",
        STRIPE_SECRET_KEY="sk_test_private_should_not_leak",
        STRIPE_WEBHOOK_SECRET="whsec_private_should_not_leak",
        STRIPE_INVOICE_WEBHOOK_SECRET="whsec_invoice_private_should_not_leak",
    )
    def test_god_mode_gets_structured_audit_without_secrets(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.god_token.key}")
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertIn("summary", response.data)
        self.assertIn("checks", response.data)
        self.assertIn("metrics", response.data)
        self.assertIn("external_verification_required", response.data)
        self.assertIn(response.data["summary"]["application_gate"], {"BLOCKED", "PASS_WITH_EXTERNAL_VERIFICATION"})

        serialized = str(response.data)
        self.assertNotIn("sk_test_private_should_not_leak", serialized)
        self.assertNotIn("whsec_private_should_not_leak", serialized)
        self.assertNotIn("whsec_invoice_private_should_not_leak", serialized)

        keys = {row["key"] for row in response.data["checks"]}
        self.assertIn("database_connectivity", keys)
        self.assertIn("stripe_core", keys)
        self.assertIn("backups_pitr", keys)
        self.assertIn("durable_media", keys)

    @override_settings(
        GOD_MODE_EMAIL_ALLOWLIST=["production-god@example.com"],
        DEBUG=True,
        SECRET_KEY="dev-insecure-secret-change-me",
    )
    def test_launch_blockers_surface_unsafe_runtime_settings(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.god_token.key}")
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        blockers = {row["key"] for row in response.data["launch_blockers"]}
        self.assertIn("debug_disabled", blockers)
        self.assertIn("secret_key", blockers)
        self.assertEqual(response.data["summary"]["application_gate"], "BLOCKED")
