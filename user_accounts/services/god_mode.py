# backend/user_accounts/services/god_mode.py
from __future__ import annotations

from django.conf import settings


def _allowlist() -> set[str]:
    """
    GOD mode allowlist from settings, defaulting to just Jacob.
    """
    raw = getattr(settings, "GOD_MODE_EMAIL_ALLOWLIST", None)
    if not raw:
        raw = ["jacoblord7@outlook.com"]

    if isinstance(raw, str):
        # allow env like: "a@b.com,c@d.com"
        parts = [p.strip() for p in raw.split(",")]
        return {p.lower() for p in parts if p}

    return {str(x).strip().lower() for x in raw if str(x).strip()}


def is_god_mode(user) -> bool:
    """
    Canonical backend source of truth.

    ✅ Recommended: ONLY email allowlist.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    email = str(getattr(user, "email", "") or "").strip().lower()
    if not email:
        return False

    return email in _allowlist()