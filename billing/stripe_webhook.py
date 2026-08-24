import json

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from user_accounts.stripe_webhook_events import claim_stripe_event, mark_stripe_event_failed, mark_stripe_event_processed

stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None) or getattr(settings, "STRIPE_API_KEY", None)


@csrf_exempt
def stripe_webhook(request):
    """Primary Stripe webhook ingress with persistent delivery idempotency.

    Business-specific side effects still live in their dedicated handlers. This
    endpoint now records every verified event id so Stripe retries cannot be
    silently processed twice as the primary billing flow is expanded.
    """

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

    if not webhook_secret:
        if not settings.DEBUG:
            return HttpResponse("Missing STRIPE_WEBHOOK_SECRET", status=500)
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            return HttpResponse("Invalid payload", status=400)
    else:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError:
            return HttpResponse("Invalid payload", status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse("Invalid signature", status=400)

    try:
        ledger, should_process = claim_stripe_event(event, endpoint="primary_billing")
    except ValueError:
        return HttpResponse("Missing Stripe event id", status=400)

    if not should_process:
        return HttpResponse(status=200, headers={"X-SyncWorks-Stripe-Duplicate": "1"})

    try:
        # This legacy ingress currently has no remaining business mutation of its
        # own. Mark verified events ignored until a dedicated handler claims them.
        mark_stripe_event_processed(ledger, ignored=True)
    except Exception as exc:
        mark_stripe_event_failed(ledger, exc)
        raise

    return HttpResponse(status=200)
