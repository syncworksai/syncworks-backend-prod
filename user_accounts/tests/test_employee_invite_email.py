"""Employee invitation email and security regression tests."""
from unittest.mock import patch
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.core import mail

from user_accounts.services.employees import invite_employee


class EmployeeInviteEmailTests(TestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="SyncWorks <no-reply@syncworksapp.com>",
    )
    @patch("user_accounts.services.employees.InviteCode.objects.create")
    @patch("user_accounts.services.employees.User.objects.get_or_create")
    @patch("user_accounts.services.employees.BusinessMember.objects.get_or_create")
    def test_employer_branded_email_sent_without_early_account_or_membership(
        self, member_get_or_create, user_get_or_create, invite_create
    ):
        invite_create.return_value = SimpleNamespace(code="one-time-abc")
        business = SimpleNamespace(id=16, name="Example Contracting")
        owner = SimpleNamespace(id=99)
        result = invite_employee(
            business=business, invited_by=owner, email="Employee@Example.com",
            seat_role="TECHNICIAN", permissions={"can_manage_team": False},
        )
        self.assertEqual(result.invite.code, "one-time-abc")
        user_get_or_create.assert_not_called()
        member_get_or_create.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "SyncWorks <no-reply@syncworksapp.com>")
        self.assertEqual(message.to, ["employee@example.com"])
        self.assertIn("Example Contracting", message.subject)
        self.assertIn("/employee/invite?code=one-time-abc", message.body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    @patch("user_accounts.services.employees.InviteCode.objects.create")
    def test_no_false_confirmation_without_delivery_backend(self, invite_create):
        invite_create.return_value = SimpleNamespace(code="abc")
        with self.assertRaisesRegex(RuntimeError, "Email delivery is not configured"):
            invite_employee(
                business=SimpleNamespace(id=16, name="Example Contracting"),
                invited_by=SimpleNamespace(id=99),
                email="employee@example.com", seat_role="TECHNICIAN",
            )
