"""Permission regressions: job titles cannot bypass revoked employee permissions."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.response import Response

from user_accounts.permissions import _user_can_manage_team
from user_accounts.viewsets.business import _can_manage_team, BusinessMemberViewSet


class BusinessTeamAuthorizationTests(SimpleTestCase):
    def test_dispatch_role_cannot_manage_team_after_permission_revoked(self):
        user = SimpleNamespace(id=23, is_authenticated=True, is_superuser=False, is_staff=False, is_platform_admin=False)
        business = SimpleNamespace(id=5, owner_id=5)
        membership = SimpleNamespace(role="DISPATCH", can_manage_team=False, is_active=True)
        with patch("user_accounts.viewsets.business.BusinessMember.objects.filter") as query:
            query.return_value.first.return_value = membership
            self.assertFalse(_can_manage_team(user, business))

    def test_job_title_is_not_authorization(self):
        user = SimpleNamespace(id=23, is_superuser=False, is_staff=False, is_platform_admin=False)
        business = SimpleNamespace(owner_id=5)
        for role in ("MANAGER", "DISPATCH", "ADMIN", "OWNER"):
            membership = SimpleNamespace(role=role, is_owner=role == "OWNER", can_manage_team=False)
            self.assertFalse(_user_can_manage_team(membership, user, business))

    def test_actual_owner_can_manage_team(self):
        user = SimpleNamespace(id=5, is_superuser=False, is_staff=False, is_platform_admin=False)
        self.assertTrue(_user_can_manage_team(None, user, SimpleNamespace(owner_id=5)))

    def test_put_uses_same_permission_checked_path_as_patch(self):
        user = SimpleNamespace(id=5, pk=5, is_authenticated=True)
        request = APIRequestFactory().put("/api/v1/business-members/23/", {"role":"MANAGER"}, format="json")
        force_authenticate(request, user=user)
        with patch.object(BusinessMemberViewSet, "partial_update", return_value=Response({"ok": True}, status=200)) as patched:
            result = BusinessMemberViewSet.as_view({"put":"update"})(request, pk="23")
        self.assertEqual(result.status_code, 200)
        patched.assert_called_once()
