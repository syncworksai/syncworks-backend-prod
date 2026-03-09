# backend/user_accounts/permissions/god_mode.py
from __future__ import annotations

from rest_framework.permissions import BasePermission
from user_accounts.services.god_mode import is_god_mode


class IsGodMode(BasePermission):
    """
    God Mode = email allowlist.
    """
    message = "Not allowed."

    def has_permission(self, request, view):
        return is_god_mode(getattr(request, "user", None))