"""PM add-on billing endpoints. Stripe is source of truth; no UI-side grants."""
import os
from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.stripe_webhook_events import (
    claim_stripe_event, mark_stripe_event_failed, mark_stripe_event_processed,
)
from .lead_billing_service import (
    is_founder, lead_billing_status, price_quote, CATALOG, subscription_for,
)
from .leasing_views import requested_workspace
from .models import PMWorkspace, PMLeadSubscription


def _checkout_configured():
    return bool(
        os.getenv("STRIPE_PM_LEAD_CHECKOUT_ENABLED", "").lower() == "true"
        and (getattr(settings, "STRIPE_SECRET_KEY", "") or "")
        and (os.getenv("STRIPE_PM_LEAD_WEBHOOK_SECRET") or getattr(settings, "STRIPE_WEBHOOK_SECRET", ""))
        and getattr(settings, "PLATFORM_BASE_URL", "")
    )


def _stripe():
    stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")
    return stripe


def _status_payload(workspace, user):
    result = lead_billing_status(workspace, user)
    result["checkout_enabled"] = _checkout_configured()
    result["features_not_yet_available"] = [key for key, value in CATALOG.items() if not value.get("available")]
    result["checkout_mode"] = "test" if str(getattr(settings, "STRIPE_SECRET_KEY", "")).startswith("sk_test_") else "live"
    return result


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pm_lead_addon_status(request):
    workspace = requested_workspace(request)
    return Response(_status_payload(workspace, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def pm_lead_checkout(request):
    workspace = requested_workspace(request)
    if is_founder(request.user):
        return Response({"founder_access": True, "detail": "Founder account has all features and unlimited inboxes. Checkout is not required."})
    if not _checkout_configured():
        return Response({"detail": "Recurring Stripe checkout is not activated for this workspace yet. No charge was created."}, status=503)
    if not isinstance(request.data, dict):
        return Response({"detail": "Provide the number of inboxes to connect."}, status=400)
    try:
        n = request.data.get("mailboxes")
        if isinstance(n, bool):
            raise ValueError
        qty = int(n)
        quote = price_quote(qty)
    except (TypeError, ValueError):
        return Response({"detail": "Select 1–100 whole mailboxes."}, status=400)
    raw_features = request.data.get("features", [])
    if not isinstance(raw_features, list) or any(f not in CATALOG for f in raw_features):
        return Response({"detail": "Invalid feature selection."}, status=400)
    unavailable = [f for f in raw_features if not CATALOG[f]["available"]]
    if unavailable:
        return Response({"detail": "Some requested features are coming soon and cannot be charged yet.", "unavailable": unavailable}, status=400)
    current = subscription_for(workspace)
    if current and current.stripe_subscription_id and current.status.upper() not in ("NONE", "CANCELED", "INCOMPLETE_EXPIRED"):
        return Response({"detail": "This PM portfolio already has a subscription. Use Manage Billing to avoid duplicate recurring charges."}, status=409)
    stripe_client = _stripe()
    if current and current.status == "PENDING" and current.stripe_checkout_session_id:
        try:
            prior = stripe_client.checkout.Session.retrieve(current.stripe_checkout_session_id)
            if prior.get("status") == "open" and prior.get("url"):
                return Response({"url": prior["url"], "checkout_session_id": prior["id"],
                                 "detail": "Resume existing secure checkout."})
            if prior.get("status") == "complete":
                return Response({"detail": "Your prior checkout completed. Waiting for Stripe subscription verification. Refresh status before starting another."}, status=409)
        except stripe.error.StripeError:
            return Response({"detail": "Unable to verify the prior checkout. No new subscription was created."}, status=502)
    try:
        if current and current.stripe_customer_id:
            customer_id = current.stripe_customer_id
        else:
            customer = stripe_client.Customer.create(
                email=request.user.email,
                name=workspace.name,
                metadata={"syncworks_pm_workspace_id": str(workspace.pk), "syncworks_user_id": str(request.user.pk)},
                idempotency_key=f"pm-leads-customer-{workspace.pk}",
            )
            customer_id = customer.id
        base = str(settings.PLATFORM_BASE_URL).rstrip("/")
        session = stripe_client.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"SyncWorks PM Lead Capture · {qty} inbox(es)",
                        "description": "Recurring mailbox lead routing and included quick replies / duplicate protection",
                    },
                    "unit_amount": quote["monthly_cents"],
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            success_url=base + "/pm/add-ons?checkout=success&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base + "/pm/add-ons?checkout=cancelled",
            client_reference_id=str(workspace.pk),
            metadata={"syncworks_scope": "pm_lead_capture", "workspace_id": str(workspace.pk),
                      "mailboxes": str(qty), "monthly_cents": str(quote["monthly_cents"])},
            subscription_data={"metadata": {
                "syncworks_scope": "pm_lead_capture", "workspace_id": str(workspace.pk),
                "mailboxes": str(qty), "monthly_cents": str(quote["monthly_cents"]),
            }},
        )
    except stripe.error.StripeError:
        return Response({"detail": "Stripe could not create recurring checkout. No checkout was started."}, status=502)
    current = current or PMLeadSubscription(workspace=workspace)
    if current.status.upper() in ("NONE", "CANCELED", "INCOMPLETE_EXPIRED"):
        current.stripe_subscription_id = ""
    current.stripe_customer_id = customer_id
    current.stripe_checkout_session_id = session.id
    current.mailbox_count = qty
    current.monthly_cents = quote["monthly_cents"]
    current.discount_percent = quote["discount_percent"]
    current.features = quote["features"]
    current.status = "PENDING"
    current.save()
    return Response({"url": session.url, "checkout_session_id": session.id, "quote": quote}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def pm_lead_billing_portal(request):
    workspace = requested_workspace(request)
    if is_founder(request.user):
        return Response({"detail": "Founder testing is free and has no paid subscription."}, status=400)
    record = subscription_for(workspace)
    if not record or not record.stripe_customer_id:
        return Response({"detail": "No Stripe billing customer exists for this PM portfolio."}, status=404)
    if not _checkout_configured():
        return Response({"detail": "Stripe billing portal is not enabled."}, status=503)
    try:
        session = _stripe().billing_portal.Session.create(
            customer=record.stripe_customer_id,
            return_url=str(settings.PLATFORM_BASE_URL).rstrip("/") + "/pm/add-ons",
        )
        return Response({"url": session.url})
    except stripe.error.StripeError:
        return Response({"detail": "Stripe billing portal could not be opened."}, status=502)


def _metadata(obj):
    return (obj.get("metadata") or {}) if hasattr(obj, "get") else {}


def _apply_subscription_event(subscription, event_type):
    metadata = _metadata(subscription)
    if metadata.get("syncworks_scope") != "pm_lead_capture":
        return False
    pk = metadata.get("workspace_id")
    try:
        workspace = PMWorkspace.objects.get(pk=int(pk), is_active=True)
    except (ValueError, TypeError, PMWorkspace.DoesNotExist):
        return False
    record, _ = PMLeadSubscription.objects.get_or_create(workspace=workspace)
    customer_id = str(subscription.get("customer") or "")
    if record.stripe_customer_id and record.stripe_customer_id != customer_id:
        raise ValueError("Stripe customer mismatch for PM portfolio.")
    subscription_id = str(subscription.get("id") or "")
    if record.stripe_subscription_id and record.stripe_subscription_id != subscription_id:
        raise ValueError("Unexpected second subscription for PM portfolio.")
    record.stripe_customer_id = customer_id
    record.stripe_subscription_id = subscription_id
    status = "CANCELED" if event_type == "customer.subscription.deleted" else str(subscription.get("status") or "NONE").upper()
    record.status = status
    record.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    end = subscription.get("current_period_end")
    record.current_period_end = datetime.fromtimestamp(int(end), tz=dt_timezone.utc) if end else None
    record.save()
    return True


def process_pm_lead_subscription_event(event):
    """Handle a signature-verified event, also used by primary billing ingress."""
    event_type = str(event.get("type") or "")
    obj = event["data"]["object"]
    applied = False
    if event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        applied = _apply_subscription_event(obj, event_type)
    elif event_type == "checkout.session.completed" and _metadata(obj).get("syncworks_scope") == "pm_lead_capture":
        wid = _metadata(obj).get("workspace_id")
        row = PMLeadSubscription.objects.filter(workspace_id=wid, stripe_checkout_session_id=str(obj.get("id") or "")).first()
        if row and str(obj.get("customer") or "") == row.stripe_customer_id:
            row.stripe_subscription_id = str(obj.get("subscription") or "")
            row.save(update_fields=["stripe_subscription_id", "updated_at"])
            # NOT ACTIVE until Stripe confirms subscription active/trialing.
            applied = True
    return applied


@csrf_exempt
def pm_lead_stripe_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    secret = (os.getenv("STRIPE_PM_LEAD_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return HttpResponse("Stripe PM webhook is not configured", status=503)
    try:
        event = _stripe().Webhook.construct_event(
            request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""), secret,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse("Invalid Stripe signature", status=400)
    try:
        log, first = claim_stripe_event(event, endpoint="pm_lead_billing")
    except ValueError:
        return HttpResponse("Missing Stripe event ID", status=400)
    if not first:
        return HttpResponse(status=200)
    try:
        applied = process_pm_lead_subscription_event(event)
        mark_stripe_event_processed(log, ignored=not applied)
    except Exception as error:
        mark_stripe_event_failed(log, error)
        return HttpResponse("Stripe billing event processing failed", status=500)
    return HttpResponse(status=200)
