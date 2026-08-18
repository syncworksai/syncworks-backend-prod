from __future__ import annotations

import os
from datetime import datetime, timezone as dt_timezone

import stripe
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog, User, UserBillingProfile

from .jarvis_product import is_test_access, load_profile, product_payload, save_profile

PRICE_ENV = {
    "PERSONAL": "STRIPE_JARVIS_PERSONAL_PRICE_ID",
    "FAMILY": "STRIPE_JARVIS_FAMILY_PRICE_ID",
    "EXECUTIVE": "STRIPE_JARVIS_EXECUTIVE_PRICE_ID",
}
LIVE_PRICE_ENV = "STRIPE_SYNC_ASSISTANT_LIVE_PRICE_ID"


def _frontend():
    return (os.getenv("FRONTEND_URL") or "https://syncworksapp.com").rstrip("/")


def _stripe_secret():
    return (os.getenv("STRIPE_SECRET_KEY") or "").strip()


class UserJarvisProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(product_payload(request.user))

    def patch(self, request):
        save_profile(request.user, request.data)
        AuditLog.objects.create(actor=request.user, action="sync_assistant.profile.updated", metadata={"fields": sorted(request.data.keys())})
        return Response(product_payload(request.user))


class UserJarvisCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate().isoformat()
        AuditLog.objects.create(actor=request.user, action="sync_assistant.day.checked_in", metadata={"local_date": today})
        return Response({"local_date": today, "checked_in_at": timezone.now(), "product_name": "SYNC Assistant"})


class UserJarvisCheckOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate().isoformat()
        reason = str(request.data.get("reason") or "MANUAL")[:40]
        AuditLog.objects.create(actor=request.user, action="sync_assistant.day.checked_out", metadata={"local_date": today, "reason": reason})
        return Response({"local_date": today, "checked_out_at": timezone.now(), "reason": reason, "product_name": "SYNC Assistant"})


class UserJarvisCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan = str(request.data.get("plan") or "").upper()
        if plan not in PRICE_ENV:
            return Response({"detail": "Choose a paid SYNC Assistant plan."}, status=400)
        secret = _stripe_secret()
        price_id = (os.getenv(PRICE_ENV[plan]) or "").strip()
        if not secret or not price_id:
            return Response({"detail": "SYNC Assistant billing is not configured yet."}, status=503)
        stripe.api_key = secret
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        frontend = _frontend()
        metadata = {"user_id": str(request.user.id), "jarvis_plan": plan, "sync_product": "ASSISTANT", "price_id": price_id}
        args = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{frontend}/upgrade?product=assistant&checkout=success",
            "cancel_url": f"{frontend}/upgrade?product=assistant&checkout=cancelled",
            "client_reference_id": str(request.user.id),
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "allow_promotion_codes": True,
        }
        if billing.stripe_customer_id:
            args["customer"] = billing.stripe_customer_id
        else:
            args["customer_email"] = request.user.email
        session = stripe.checkout.Session.create(**args)
        return Response({"url": session.url})


class UserSyncAssistantLiveCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if is_test_access(request.user):
            save_profile(request.user, {"live": {"enabled": True, "access": True, "subscription_status": "test_access"}})
            return Response({"activated": True, "test_access": True, "profile": product_payload(request.user)})
        secret = _stripe_secret()
        price_id = (os.getenv(LIVE_PRICE_ENV) or "").strip()
        if not secret or not price_id:
            return Response({"detail": "SYNC Assistant Live billing is not configured yet."}, status=503)
        stripe.api_key = secret
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        frontend = _frontend()
        metadata = {"user_id": str(request.user.id), "sync_product": "ASSISTANT_LIVE", "sync_addon": "LIVE", "price_id": price_id}
        args = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{frontend}/upgrade?product=assistant&live=success",
            "cancel_url": f"{frontend}/upgrade?product=assistant&live=cancelled",
            "client_reference_id": str(request.user.id),
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "allow_promotion_codes": True,
        }
        if billing.stripe_customer_id:
            args["customer"] = billing.stripe_customer_id
        else:
            args["customer_email"] = request.user.email
        session = stripe.checkout.Session.create(**args)
        return Response({"url": session.url})


class UserJarvisPortalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        secret = _stripe_secret()
        if not secret or not billing.stripe_customer_id:
            return Response({"detail": "No billing account is available yet."}, status=400)
        stripe.api_key = secret
        portal = stripe.billing_portal.Session.create(customer=billing.stripe_customer_id, return_url=f"{_frontend()}/upgrade?product=assistant")
        return Response({"url": portal.url})


def _set_live_subscription(user, *, access: bool, status: str, subscription_id: str = ""):
    _, profile = load_profile(user)
    current = profile.get("live") or {}
    save_profile(user, {"live": {**current, "access": access, "enabled": access or bool(current.get("enabled")), "subscription_status": status, "subscription_id": subscription_id or current.get("subscription_id", "")}})


class UserJarvisWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        secret = (os.getenv("STRIPE_JARVIS_WEBHOOK_SECRET") or "").strip()
        if not secret:
            return Response({"detail": "Webhook is not configured."}, status=503)
        try:
            event = stripe.Webhook.construct_event(request.body, request.headers.get("Stripe-Signature", ""), secret)
        except Exception:
            return Response(status=400)
        event_type = event["type"]
        obj = event["data"]["object"]
        metadata = obj.get("metadata") or {}
        user_id = metadata.get("user_id") or obj.get("client_reference_id")
        if not user_id:
            return Response({"received": True})
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"received": True})

        is_live = metadata.get("sync_addon") == "LIVE" or metadata.get("sync_product") == "ASSISTANT_LIVE"
        if event_type == "checkout.session.completed":
            billing, _ = UserBillingProfile.objects.get_or_create(user=user)
            billing.stripe_customer_id = obj.get("customer") or billing.stripe_customer_id
            if is_live:
                subscription_id = obj.get("subscription") or ""
                _set_live_subscription(user, access=True, status="active", subscription_id=subscription_id)
                AuditLog.objects.create(actor=user, action="sync_assistant.live.activated", metadata={"subscription_id": subscription_id})
            else:
                plan = str(metadata.get("jarvis_plan") or "PERSONAL").upper()
                save_profile(user, {"plan": plan, "onboarding_complete": True})
                billing.stripe_subscription_id = obj.get("subscription") or billing.stripe_subscription_id
                billing.subscription_status = "active"
                AuditLog.objects.create(actor=user, action="sync_assistant.subscription.activated", metadata={"plan": plan})
            billing.save()

        if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            status = str(obj.get("status") or "inactive")
            active = event_type != "customer.subscription.deleted" and status in {"active", "trialing"}
            if is_live:
                _set_live_subscription(user, access=active, status=status, subscription_id=obj.get("id") or "")
                AuditLog.objects.create(actor=user, action="sync_assistant.live.subscription_changed", metadata={"status": status, "active": active})
            else:
                billing, _ = UserBillingProfile.objects.get_or_create(user=user)
                billing.subscription_status = status
                billing.stripe_subscription_id = obj.get("id") or billing.stripe_subscription_id
                billing.subscription_cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
                period_end = obj.get("current_period_end")
                if period_end:
                    billing.subscription_current_period_end = datetime.fromtimestamp(period_end, tz=dt_timezone.utc)
                billing.save()
        return Response({"received": True})
