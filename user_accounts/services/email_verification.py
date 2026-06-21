from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from user_accounts.models.user import (
    EmailVerificationChallenge,
)


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def get_client_ip(request) -> str | None:
    forwarded = request.META.get(
        "HTTP_X_FORWARDED_FOR",
        "",
    )

    if forwarded:
        return forwarded.split(",")[0].strip() or None

    return (
        request.META.get("REMOTE_ADDR")
        or None
    )


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def challenge_expiry_seconds() -> int:
    return int(
        getattr(
            settings,
            "AUTH_EMAIL_CODE_EXPIRY_SECONDS",
            600,
        )
    )


def resend_cooldown_seconds() -> int:
    return int(
        getattr(
            settings,
            "AUTH_EMAIL_RESEND_COOLDOWN_SECONDS",
            60,
        )
    )


def max_attempts() -> int:
    return int(
        getattr(
            settings,
            "AUTH_EMAIL_MAX_VERIFY_ATTEMPTS",
            6,
        )
    )


def _rate_limit_key(
    *,
    email: str,
    ip_address: str | None,
) -> str:
    return (
        "auth-email-verification:"
        f"{email}:{ip_address or 'unknown'}"
    )


def enforce_start_rate_limit(
    *,
    email: str,
    ip_address: str | None,
) -> None:
    key = _rate_limit_key(
        email=email,
        ip_address=ip_address,
    )

    count = cache.get(key, 0)

    limit = int(
        getattr(
            settings,
            "AUTH_EMAIL_START_LIMIT_PER_HOUR",
            8,
        )
    )

    if count >= limit:
        raise Throttled(
            detail=(
                "Too many verification requests. "
                "Try again later."
            )
        )

    if count == 0:
        cache.set(key, 1, timeout=3600)
    else:
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, count + 1, timeout=3600)


def send_verification_email(
    *,
    email: str,
    code: str,
) -> None:
    subject = "Your SyncWorks verification code"

    body = (
        "Your SyncWorks verification code is:\n\n"
        f"{code}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not request this code, "
        "you can ignore this email."
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "SyncWorks <no-reply@syncworks.ai>",
        ),
        recipient_list=[email],
        fail_silently=False,
    )


@transaction.atomic
def create_challenge(
    *,
    email: str,
    purpose: str,
    ip_address: str | None,
    user_agent: str,
) -> EmailVerificationChallenge:
    email = normalize_email(email)

    enforce_start_rate_limit(
        email=email,
        ip_address=ip_address,
    )

    now = timezone.now()
    code = generate_code()

    (
        EmailVerificationChallenge.objects
        .filter(
            email__iexact=email,
            purpose=purpose,
            verified_at__isnull=True,
            consumed_at__isnull=True,
        )
        .update(consumed_at=now)
    )

    challenge = EmailVerificationChallenge(
        email=email,
        purpose=purpose,
        expires_at=(
            now
            + timedelta(
                seconds=challenge_expiry_seconds()
            )
        ),
        last_sent_at=now,
        requested_ip=ip_address,
        user_agent=(user_agent or "")[:2000],
    )

    challenge.set_code(code)
    challenge.save()

    send_verification_email(
        email=email,
        code=code,
    )

    return challenge


@transaction.atomic
def resend_challenge(
    *,
    challenge: EmailVerificationChallenge,
) -> EmailVerificationChallenge:
    challenge = (
        EmailVerificationChallenge.objects
        .select_for_update()
        .get(pk=challenge.pk)
    )

    if challenge.is_consumed:
        raise ValidationError(
            "This verification request is no longer active."
        )

    now = timezone.now()

    if challenge.last_sent_at:
        elapsed = (
            now - challenge.last_sent_at
        ).total_seconds()

        remaining = (
            resend_cooldown_seconds()
            - int(elapsed)
        )

        if remaining > 0:
            raise Throttled(
                wait=remaining,
                detail=(
                    "Please wait before requesting "
                    "another code."
                ),
            )

    code = generate_code()

    challenge.set_code(code)
    challenge.expires_at = (
        now
        + timedelta(
            seconds=challenge_expiry_seconds()
        )
    )

    challenge.last_sent_at = now
    challenge.resend_count += 1
    challenge.attempt_count = 0

    challenge.save(
        update_fields=[
            "code_hash",
            "expires_at",
            "last_sent_at",
            "resend_count",
            "attempt_count",
        ]
    )

    send_verification_email(
        email=challenge.email,
        code=code,
    )

    return challenge