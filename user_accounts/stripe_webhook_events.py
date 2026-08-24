from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from user_accounts.models.stripe_webhook_event import StripeWebhookEvent


def _value(source, key, default=None):
    if hasattr(source, "get"):
        try:
            return source.get(key, default)
        except Exception:
            return default
    return getattr(source, key, default)


def claim_stripe_event(event, *, endpoint: str) -> tuple[StripeWebhookEvent, bool]:
    """Claim a verified Stripe event before running any side effect.

    Returns `(ledger_row, should_process)`. Already processed/ignored/in-flight
    duplicate deliveries return `False`. A prior FAILED row is reopened so a
    legitimate Stripe retry can attempt the handler again.
    """

    event_id = str(_value(event, "id", "") or "").strip()
    event_type = str(_value(event, "type", "") or "").strip()
    data = _value(event, "data", {}) or {}
    obj = _value(data, "object", {}) or {}
    object_id = str(_value(obj, "id", "") or "").strip()
    livemode = bool(_value(event, "livemode", False))
    api_version = str(_value(event, "api_version", "") or "").strip()

    if not event_id:
        raise ValueError("Stripe event is missing its event id.")

    try:
        with transaction.atomic():
            row = StripeWebhookEvent.objects.create(
                stripe_event_id=event_id,
                event_type=event_type,
                endpoint=str(endpoint or "")[:120],
                object_id=object_id,
                livemode=livemode,
                api_version=api_version[:64],
            )
            return row, True
    except IntegrityError:
        with transaction.atomic():
            row = StripeWebhookEvent.objects.select_for_update().get(stripe_event_id=event_id)
            row.attempts += 1
            should_retry = row.status == StripeWebhookEvent.Status.FAILED
            if should_retry:
                row.status = StripeWebhookEvent.Status.RECEIVED
                row.last_error = ""
                row.processed_at = None
            row.save(update_fields=["attempts", "status", "last_error", "processed_at", "updated_at"])
            return row, should_retry


def mark_stripe_event_processed(row: StripeWebhookEvent, *, ignored: bool = False) -> None:
    row.status = StripeWebhookEvent.Status.IGNORED if ignored else StripeWebhookEvent.Status.PROCESSED
    row.last_error = ""
    row.processed_at = timezone.now()
    row.save(update_fields=["status", "last_error", "processed_at", "updated_at"])


def mark_stripe_event_failed(row: StripeWebhookEvent, error: Exception | str) -> None:
    row.status = StripeWebhookEvent.Status.FAILED
    row.last_error = str(error)[:4000]
    row.processed_at = timezone.now()
    row.save(update_fields=["status", "last_error", "processed_at", "updated_at"])
