from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import Business, BusinessMember, CommunicationPreference
from user_accounts.viewsets.communication_preferences import CurrentCommunicationPreferenceAPIView


class CommunicationPreferenceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="communication-owner",
            email="communication-owner@example.com",
            password="test-pass-123",
        )
        self.employee = User.objects.create_user(
            username="communication-employee",
            email="communication-employee@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Automated Inbox Company",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.employee,
            role="TECHNICIAN",
            is_active=True,
        )
        self.factory = APIRequestFactory()
        self.view = CurrentCommunicationPreferenceAPIView.as_view()

    def call(self, user, method="get", scope="BUSINESS", data=None):
        request = getattr(self.factory, method)(
            f"/api/v1/communication-preferences/current/?scope={scope}",
            data=data or {},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=user)
        return self.view(request)

    def test_business_scope_defaults_are_automated(self):
        response = self.call(self.owner)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["internal_inbox_enabled"])
        self.assertTrue(response.data["email_notifications_enabled"])
        self.assertTrue(response.data["automatic_updates_enabled"])
        self.assertEqual(response.data["assignment_mode"], "AUTO")
        self.assertFalse(response.data["sms_notifications_enabled"])

    def test_employee_gets_business_scoped_preferences(self):
        response = self.call(self.employee)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["scope"], "BUSINESS")

    def test_sms_requires_paid_addon_and_consent(self):
        response = self.call(
            self.owner,
            method="patch",
            data={"sms_notifications_enabled": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("sms_notifications_enabled", response.data)

    def test_internal_inbox_remains_required(self):
        response = self.call(
            self.owner,
            method="patch",
            data={
                "internal_inbox_enabled": False,
                "email_notifications_enabled": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["internal_inbox_enabled"])
        self.assertFalse(response.data["email_notifications_enabled"])
