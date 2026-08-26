from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import AuditLog, Business, StripeConnectProfile, Ticket


User = get_user_model()


class SyncRoleAwareBriefingTests(APITestCase):
    def make_user(self, username, email):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="test-password-123",
        )
        token = Token.objects.create(user=user)
        return user, token

    def authenticate(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_briefing_requires_authentication(self):
        response = self.client.get("/api/v1/sync-ai/briefing/")
        self.assertEqual(response.status_code, 401)

    def test_personal_briefing_returns_structured_sections(self):
        user, token = self.make_user("briefing-user", "briefing@example.com")
        PersonalCalendarEvent.objects.create(
            owner=user,
            title="Workout",
            start_at=timezone.now() + timedelta(hours=2),
        )
        Ticket.objects.create(
            customer=user,
            work_title="Kitchen sink repair",
            status=Ticket.Status.NEW,
        )
        self.authenticate(token)

        response = self.client.get("/api/v1/sync-ai/briefing/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("sections", response.data)
        section_ids = {section["id"] for section in response.data["sections"]}
        self.assertIn("personal_requests", section_ids)
        self.assertIn("calendar", section_ids)
        self.assertFalse(response.data["roles"]["god_mode"])
        self.assertTrue(
            AuditLog.objects.filter(
                actor=user,
                action="sync_ai.briefing.completed",
            ).exists()
        )

    def test_standard_user_cannot_access_god_mode_report(self):
        _, token = self.make_user("standard-user", "standard@example.com")
        self.authenticate(token)

        response = self.client.get("/api/v1/sync-ai/briefing/god-mode/")

        self.assertEqual(response.status_code, 403)

    def test_god_mode_report_contains_platform_and_business_readiness(self):
        user, token = self.make_user("jacob", "jacoblord7@outlook.com")
        business = Business.objects.create(
            owner=user,
            name="Quantum Edge",
            is_active=True,
        )
        StripeConnectProfile.objects.create(
            business=business,
            onboarding_completed=False,
            charges_enabled=False,
            payouts_enabled=False,
        )
        Ticket.objects.create(
            customer=user,
            assigned_business=business,
            work_title="New business ticket",
            status=Ticket.Status.NEW,
        )
        self.authenticate(token)

        response = self.client.get("/api/v1/sync-ai/briefing/god-mode/")

        self.assertEqual(response.status_code, 200)
        section_ids = {section["id"] for section in response.data["sections"]}
        self.assertIn("god_mode", section_ids)
        god_mode = next(
            section for section in response.data["sections"] if section["id"] == "god_mode"
        )
        stripe_item = next(
            item
            for item in god_mode["items"]
            if item["label"] == "Businesses missing Stripe"
        )
        self.assertGreaterEqual(stripe_item["value"], 1)
