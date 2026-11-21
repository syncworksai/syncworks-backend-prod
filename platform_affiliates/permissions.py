from __future__ import annotations

from rest_framework.permissions import BasePermission

from user_accounts.models import Business, BusinessMember
from user_accounts.services.god_mode import is_god_mode


class IsGodModeAffiliateAdmin(BasePermission):
    message = "God Mode access required."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and is_god_mode(request.user))


class IsCustomerAffiliateApplicant(BasePermission):
    message = "Affiliate applications are limited to customers and verified business owners."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        if is_god_mode(user):
            return True

        owns_business = Business.objects.filter(owner=user).exists()
        active_business_member = BusinessMember.objects.filter(user=user, is_active=True).exists()

        if owns_business:
            return True

        # Verified OWNER memberships qualify; employee roles do not.
        owns_via_membership = BusinessMember.objects.filter(
            user=user, is_active=True, role=BusinessMember.ROLE_OWNER
        ).exists()
        if owns_via_membership:
            return True

        return not active_business_member