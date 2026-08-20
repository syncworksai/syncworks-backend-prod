# backend/user_accounts/services/god_mode.py
from __future__ import annotations

FOUNDER_GOD_MODE_EMAIL = "jacoblord7@outlook.com"


def is_god_mode(user) -> bool:
    """Canonical founder-only God Mode authorization.

    Delegated God Mode access must be introduced later with an explicit audited
    permission model. Staff, superuser and platform-admin flags do not grant God Mode.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    email = str(getattr(user, "email", "") or "").strip().lower()
    return email == FOUNDER_GOD_MODE_EMAIL
