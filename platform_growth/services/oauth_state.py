from __future__ import annotations

import secrets
from datetime import timedelta

from django.utils import timezone


def generate_state_token() -> str:
    """Generate a URL-safe random OAuth state token."""
    return secrets.token_urlsafe(32)


def default_expiry(*, minutes: int = 15):
    """Return a default OAuth state expiry datetime."""
    return timezone.now() + timedelta(minutes=minutes)


def is_state_expired(expires_at) -> bool:
    """Best-effort expiration check for GrowthOAuthState records."""
    if not expires_at:
        return True
    return expires_at <= timezone.now()
