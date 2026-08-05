from __future__ import annotations

import os

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog, UserBillingProfile

from .models import JarvisDaySession, JarvisProfile
from .services import billing_snapshot, entitlements, module_catalog, setup_score

PLAN_PRICE_ENV = {
    JarvisProfile.Plan.PERSONAL: "STRIPE_JARVIS_PERSONAL_PRICE_ID",
    JarvisProfile.Plan.FAMILY: "STRIPE_JARVIS_FAMILY_PRICE_ID",
    JarvisProfile.Plan.EXECUTIVE: "STRIPE_JARVIS_EXECUTIVE_PRICE_ID",
}


def _profile(user):
    return JarvisProfile.objects.get_or_create(user=user)[0]


def _payload(user, profile):
    return {
        "assistant_name": profile.assistant_name,
        "tone": profile.tone,
        "briefing_length": profile.briefing_length,
        "template": profile.template,
        "wake_time": profile.wake_time,
        "bedtime": profile.bedtime,
        "quiet_hours_enabled": profile.quiet_hours_enabled,
        "goals": profile.goals,
        "modules": profile.modules,
        "permissions": profile.permissions,
        "onboarding_step": profile.onboarding_step,
        "onboarding_complete": profile.onboarding_complete,
        "setup_score": setup_score(user, profile),
        "entitlements": entitlements(user, profile),
        "billing": billing_snapshot(user, profile),
        "module_catalog": module_catalog(user, profile),
        "plans": [
            {"id": "BASIC", "name": "Basic", "price": 0, "description": "Marketplace, service requests, manual calendar and tasks, limited briefing."},
            {"id": "PERSONAL", "name": "Personal AI", "price": 12.99, "description": "Voice briefings, overnight preparation, email and calendar intelligence, Health and Money."},
            {"id": "FAMILY", "name": "Family", "price": 22.99, "description": "Personal AI plus shared schedules, household coordination, and family alerts."},
            {"id": "EXECUTIVE", "name": "Executive", "price": 34.99, "description": "Multiple businesses, rental properties, affiliates, deeper reports, and approved actions."},
        ],
    }


class JarvisProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_payload(request.user, _profile(request.user)))

    def patch(self, request):
        profile = _profile(request.user)
        scalar_fields = ("assistant_name", "tone", "briefing_length", "template", "wake_time", "bedtime", "quiet_hours_enabled", "onboarding_step", "onboarding_complete")
        json_fields = ("goals", "modules", "permissions")
        for field in scalar_fields:
            if field in request.data:
                setattr(profile, field, request.data[field])
        for field in json_fields:
            if field in request.data and isinstance(request.data[field], (dict, list)):
                setattr(profile, field, request.data[field])
        profile.save()
        AuditLog.objects.create(actor=request.user, action="jarvis.profile.updated", metadata={"fields": sorted(request.data.keys())})
        return Response(_payload(request.user, profile))


class JarvisCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate()
        session, _ = JarvisDaySession.objects.get_or_create(user=request.user, local_date=today)
        if not session.checked_in_at:
            session.checked_in_at = timezone.now()
            session.save(update_fields=("checked_in_at", "updated_at"))
        return Response({"local_date": today, "checked_in_at": session.checked_in_at, "checked_out_at": session.checked_out_at})


class JarvisCheckOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localdate()
        session, _ = JarvisDaySession.objects.get_or_create(user=request.user, local_date=today)
        session.checked_out_at = timezone.now()
        session.check_out_reason = str(request.data.get("reason") or "MANUAL")[:40]
        session.save(update_fields=("checked_out_at", "check_out_reason", "updated_at"))
        return Response({"local_date": today, "checked_in_at": session.checked_in_at, "checked_out_at": session.checked_out_at})


class JarvisCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan = str(request.data.get("plan") or "").upper()
        if plan not in PLAN_PRICE_ENV:
            return Response({"detail": "Choose a paid Jarvis plan."}, status=400)
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        price_id = (os.getenv(PLAN_PRICE_ENV[plan]) or "").strip()
        if not secret or not price_id:
            return Response({"detail": "Jarvis billing is not configured yet."}, status=503)
        stripe.api_key = secret
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        customer_id = billing.stripe_customer_id or None
        frontend = (os.getenv("FRONTEND_BASE_URL") or "https://syncworksapp.com").rstrip("/")
        kwargs = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{frontend}/jarvis/setup?checkout=success",
            "cancel_url": f"{frontend}/jarvis/setup?checkout=cancelled",
            "client_reference_id": str(request.user.id),
            "metadata": {"user_id": str(request.user.id), "jarvis_plan": plan},
            "subscription_data": {"metadata": {"user_id": str(request.user.id), "jarvis_plan": plan}},
            "allow_promotion_codes": True,
        }
        if customer_id:
            kwargs["customer"] = customer_id
        else:
            kwargs["customer_email"] = request.user.email
        checkout = stripe.checkout.Session.create(**kwargs)
        return Response({"url": checkout.url})


class JarvisPortalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
        billing, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        if not secret or not billing.stripe_customer_id:
            return Response({"detail": "No Stripe customer is available."}, status=400)
        stripe.api_key = secret
        frontend = (os.getenv("FRONTEND_BASE_URL") or "https://syncworksapp.com").rstrip("/")
        portal = stripe.billing_portal.Session.create(customer=billing.stripe_customer_id, return_url=f"{frontend}/jarvis/setup")
        return Response({"url": portal.url})


class JarvisWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        secret = (os.getenv("STRIPE_JARVIS_WEBHOOK_SECRET") or "").strip()
        try:
            event = stripe.Webhook.construct_event(request.body, request.headers.get("Stripe-Signature", ""), secret)
        except Exception:
            return Response(status=400)
        obj = event["data"]["object"]
        metadata = obj.get("metadata") or {}
        user_id = metadata.get("user_id")
        plan = metadata.get("jarvis_plan")
        if event["type"] == "checkout.session.completed" and user_id:
            with transaction.atomic():
                profile = JarvisProfile.objects.get(user_id=user_id)
                billing, _ = UserBillingProfile.objects.get_or_create(user_id=user_id)
                profile.plan = plan or profile.plan
                profile.subscription_status = JarvisProfile.Status.ACTIVE
                profile.stripe_price_id = obj.get("amount_total") and str(obj.get("amount_total")) or profile.stripe_price_id
                profile.save()
                billing.stripe_customer_id = obj.get("customer") or billing.stripe_customer_id
                billing.stripe_subscription_id = obj.get("subscription") or billing.stripe_subscription_id
                billing.subscription_status = "active"
                billing.save()
        return Response({"received": True})
