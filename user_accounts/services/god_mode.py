# backend/user_accounts/services/god_mode.py
from __future__ import annotations

# Founder lock: God Mode is intentionally single-user until delegated access is
# designed with an explicit permission/audit model. Environment variables must
# not be able to silently widen this boundary.
GOD_MODE_EMAIL = "jacoblord7@outlook.com"


def is_god_mode(user) -> bool:
    """Canonical backend source of truth for God Mode access."""
    if not user or not getattr(user, "is_authenticated", False):
        return False

    email = str(getattr(user, "email", "") or "").strip().lower()
    return bool(email) and email == GOD_MODE_EMAIL
