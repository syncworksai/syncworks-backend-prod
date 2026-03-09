# backend/billing/stripe_webhook.py
import json
import stripe

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

# ✅ IMPORTANT:
# Set these in your environment / settings:
# STRIPE_SECRET_KEY=sk_test_...
# STRIPE_WEBHOOK_SECRET=whsec_...   (from Stripe Dashboard or Stripe CLI)
stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None) or getattr(settings, "STRIPE_API_KEY", None)


@csrf_exempt
def stripe_webhook(request):
    """
    Handles Stripe webhook events.
    MVP: we care about checkout.session.completed for card setup / subscription start.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

    # If you haven't configured the secret yet, allow in DEBUG for local testing
    # (In production, you MUST have STRIPE_WEBHOOK_SECRET set.)
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

    event_type = event.get("type", "")
    data_obj = (event.get("data") or {}).get("object") or {}

    # ✅ TODO: wire this to your DB
    # At minimum, you'll want to:
    # - identify business (via metadata you attach when creating session)
    # - store stripe customer id
    # - store card brand/last4/exp
    # - mark stripe_setup_complete = True

    if event_type == "checkout.session.completed":
        # For Checkout sessions, Stripe session object:
        # data_obj["id"], data_obj["customer"], data_obj.get("mode"), etc.
        # If you created the session, you should set metadata like:
        # metadata={"business_id": "...", "user_id": "..."}
        # so you can update the correct Business.
        #
        # Example:
        # business_id = (data_obj.get("metadata") or {}).get("business_id")
        # customer_id = data_obj.get("customer")
        pass

    return HttpResponse(status=200)
