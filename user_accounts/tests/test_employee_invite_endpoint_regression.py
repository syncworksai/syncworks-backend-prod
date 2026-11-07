"""Regression coverage for the business employee invitation endpoint."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.viewsets.business import BusinessTeamViewSet


class EmployeeInviteEndpointTests(SimpleTestCase):
    def test_invite_passes_validated_fields_only_without_duplicate_email(self):
        request = APIRequestFactory().post(
            "/api/v1/businesses/16/invite-employee/",
            {
                "email": "team@example.com",
                "role": "TECHNICIAN",
                "permissions": {
                    "can_manage_team": True,
                    "can_manage_settings": True,
                },
                "first_name": "Test",
                "last_name": "Employee",
            },
            format="json",
        )
        force_authenticate(
            request, user=SimpleNamespace(id=1, pk=1, is_authenticated=True)
        )
        business = SimpleNamespace(id=16)

        with (
            patch.object(BusinessTeamViewSet, "_get_business", return_value=business),
            patch("user_accounts.viewsets.business._require_team_manage_access"),
            patch("user_accounts.viewsets.business.invite_employee") as invite,
            patch("user_accounts.viewsets.business.EmployeeInviteResponseSerializer") as response_serializer,
        ):
            invite.return_value = SimpleNamespace(invite=object())
            response_serializer.return_value.data = {"email": "team@example.com"}

            response = BusinessTeamViewSet.as_view({"post": "invite_employee"})(
                request, pk="16"
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "team@example.com")
        invite.assert_called_once()
        kwargs = invite.call_args.kwargs
        self.assertEqual(kwargs["business"], business)
        self.assertEqual(kwargs["email"], "team@example.com")
        self.assertEqual(kwargs["seat_role"], "TECHNICIAN")
        self.assertEqual(
            kwargs["permissions"],
            {"can_manage_team": True, "can_manage_settings": True},
        )
        self.assertEqual(
            set(kwargs),
            {"business", "invited_by", "email", "seat_role", "permissions"},
        )
