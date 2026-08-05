from __future__ import annotations

import os

import stripe
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog, User, UserBillingProfile

from .jarvis_product import product_payload, save_profile

PRICE_ENV = {
    "PERSONAL": "STRIPE_JARVIS_PERSONAL_PRICE_ID",
    "FAMILY": "STRIPE_JARVIS_FAMILY_PRICE_ID",
    "EXECUTIVE": "STRIPE_JARVIS_EXECUTIVE_PRICE_ID",
}


class UserJarvisProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(product_payload(request.user))

    def patch(self, request):
        save_profile(request.user, request.data)
        AuditLog.objects.create(actor=request.user, action="jarvis.profile.updated", metadata={"fields": sorted(request.data.keys())})
        return Response(product_payload(request.user))


class UserJarvisCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate().isoformat()
        AuditLog.objects.create(actor=request.user, action="jarvis.day.checked_in", metadata={"local_date": today})
        return Response({"local_date": today, "checked_in_at": timezone.now()})


class UserJarvisCheckOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate().isoformat()
        reason = str(request.data.get("reason") or "MANUAL")[:40]
        AuditLog.objects.create(actor=request.user, action="jarvis.day.checked_out", metadata={"local_date": today, "reason": reason})
        return Response({"local_date": today, "checked_out_at": timezone.now(), "reason": reason})


class UserJarvisCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan = str(request.data.get("plan") or "").upper()
        if plan not in PRICE_ENV:
            return Response({"detail": "Choose a paid Jarvis plan."}, status=400)
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        price_id = (os.getenv(PRICE_ENV[plan]) or "").strip()
        if not secret or not price_id:
            return Response({"detail": "Jarvis billing is not configured yet."}, status=503)
        stripe.api_key = secret
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        frontend = (os.getenv("FRONTEND_URL") or "https://syncworksapp.com").rstrip("/")
        args = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{frontend}/jarvis/setup?checkout=success",
            "cancel_url": f"{frontend}/jarvis/setup?checkout=cancelled",
            "client_reference_id": str(request.user.id),
            "metadata": {"user_id": str(request.user.id), "jarvis_plan": plan, "price_id": price_id},
            "subscription_data": {"metadata": {"user_id": str(request.user.id), "jarvis_plan": plan, "price_id": price_id}},
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
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        if not secret or not billing.stripe_customer_id:
            return Response({"detail": "No billing account is available yet."}, status=400)
        stripe.api_key = secret
        frontend = (os.getenv("FRONTEND_URL") or "https://syncworksapp.com").rstrip("/")
        portal = stripe.billing_portal.Session.create(customer=billing.stripe_customer_id, return_url=f"{frontend}/jarvis/setup")
        return Response({"url": portal.url})


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
        obj = event["data"]["object"]
        metadata = obj.get("metadata") or {}
        user_id = metadata.get("user_id") or obj.get("client_reference_id")
        if event["type"] == "checkout.session.completed" and user_id:
            user = User.objects.get(id=user_id)
            plan = str(metadata.get("jarvis_plan") or "PERSONAL").upper()
            save_profile(user, {"plan": plan, "onboarding_complete": True})
            billing, _ = UserBillingProfile.objects.get_or_create(user=user)
            billing.stripe_customer_id = obj.get("customer") or billing.stripe_customer_id
            billing.stripe_subscription_id = obj.get("subscription") or billing.stripe_subscription_id
            billing.subscription_status = "active"
            billing.save()
            AuditLog.objects.create(actor=user, action="jarvis.subscription.activated", metadata={"plan": plan})
        return Response({"received": True})
