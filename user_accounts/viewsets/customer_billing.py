# backend/user_accounts/viewsets/customer_billing.py
from __future__ import annotations

import stripe
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.customer_settings import CustomerSettings


def _platform_base_url() -> str:
    return (getattr(settings, "PLATFORM_BASE_URL", "") or "").rstrip("/") or "http://localhost:5174"


def _stripe_key() -> str:
    return getattr(settings, "STRIPE_SECRET_KEY", "") or ""


def _stripe_enabled() -> bool:
    return bool(_stripe_key())


def _get_or_create_customer_settings(user) -> CustomerSettings:
    obj = CustomerSettings.objects.filter(user_id=user.id).first()
    if obj:
        return obj
    return CustomerSettings.objects.create(user=user)


def _user_display_name(user) -> str:
    email = getattr(user, "email", "") or ""
    username = getattr(user, "username", "") or ""
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    name = f"{first} {last}".strip()
    return name or username or email or f"User {getattr(user, 'id', '')}"


def _get_or_create_stripe_customer(user, cs: CustomerSettings) -> str:
    """
    Ensures a Stripe Customer exists and returns the customer_id.
    Stores on CustomerSettings.stripe_customer_id.
    """
    if cs.stripe_customer_id:
        return cs.stripe_customer_id

    stripe.api_key = _stripe_key()

    email = getattr(user, "email", "") or ""
    name = _user_display_name(user)

    customer = stripe.Customer.create(
        email=email or None,
        name=name or None,
        metadata={"user_id": str(user.id)},
    )
    cs.stripe_customer_id = customer["id"]
    cs.save(update_fields=["stripe_customer_id"])
    return cs.stripe_customer_id


def _payment_payload(cs: CustomerSettings) -> dict:
    return {
        "has_card_on_file": bool(cs.stripe_payment_method_id),
        "brand": cs.stripe_payment_method_brand or None,
        "last4": cs.stripe_payment_method_last4 or None,
        "exp_month": cs.stripe_payment_method_exp_month,
        "exp_year": cs.stripe_payment_method_exp_year,
    }


class CustomerSetupCardAPIView(APIView):
    """
    POST /billing/customer/setup-card/
    Returns Stripe Checkout URL (mode=setup) for saving a payment method.

    success_url includes session_id so frontend can call:
      POST /billing/customer/setup-card/complete/ { session_id }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _stripe_enabled():
            return Response({"detail": "Stripe is not configured (missing STRIPE_SECRET_KEY)."}, status=500)

        stripe.api_key = _stripe_key()

        cs = _get_or_create_customer_settings(request.user)
        customer_id = _get_or_create_stripe_customer(request.user, cs)

        base = _platform_base_url()
        success = f"{base}/customer/settings?card_setup=success&session_id={{CHECKOUT_SESSION_ID}}"
        cancel = f"{base}/customer/settings?card_setup=cancelled"

        # Metadata used to verify correct user on complete
        session = stripe.checkout.Session.create(
            mode="setup",
            customer=customer_id,
            success_url=success,
            cancel_url=cancel,
            payment_method_types=["card"],
            metadata={"user_id": str(request.user.id)},
        )

        return Response({"url": session["url"]})


class CustomerSetupCardCompleteAPIView(APIView):
    """
    POST /billing/customer/setup-card/complete/
    Body: { "session_id": "cs_..." }

    Retrieves Checkout session -> SetupIntent -> PaymentMethod.
    Stores PM id + display fields on CustomerSettings.

    NOTE:
    - We do NOT store any card numbers (only brand/last4/exp metadata).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _stripe_enabled():
            return Response({"detail": "Stripe is not configured (missing STRIPE_SECRET_KEY)."}, status=500)

        session_id = str((request.data or {}).get("session_id") or "").strip()
        if not session_id or not session_id.startswith("cs_"):
            return Response({"detail": "Missing or invalid session_id."}, status=400)

        stripe.api_key = _stripe_key()

        cs = _get_or_create_customer_settings(request.user)
        customer_id = _get_or_create_stripe_customer(request.user, cs)

        # Retrieve session
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except Exception:
            return Response({"detail": "Unable to retrieve checkout session."}, status=400)

        if session.get("mode") != "setup":
            return Response({"detail": "Checkout session is not setup mode."}, status=400)

        # Security: ensure session belongs to this user/customer
        session_customer = session.get("customer")
        if session_customer and session_customer != customer_id:
            return Response({"detail": "Session does not belong to this customer."}, status=403)

        meta_user_id = None
        md = session.get("metadata") or {}
        if isinstance(md, dict):
            meta_user_id = md.get("user_id")

        if meta_user_id and str(meta_user_id) != str(request.user.id):
            return Response({"detail": "Session does not belong to this user."}, status=403)

        setup_intent_id = session.get("setup_intent")
        if not setup_intent_id:
            return Response({"detail": "Setup intent not found on session."}, status=400)

        try:
            setup_intent = stripe.SetupIntent.retrieve(setup_intent_id)
        except Exception:
            return Response({"detail": "Unable to retrieve setup intent."}, status=400)

        pm_id = setup_intent.get("payment_method")
        if not pm_id:
            return Response({"detail": "Payment method not found on setup intent."}, status=400)

        # Attach PM to customer (safe if already attached)
        try:
            stripe.PaymentMethod.attach(pm_id, customer=customer_id)
        except Exception:
            # Often already attached — ignore.
            pass

        # Set default for invoices/subscriptions later
        try:
            stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id})
        except Exception:
            # Non-fatal
            pass

        try:
            pm = stripe.PaymentMethod.retrieve(pm_id)
        except Exception:
            return Response({"detail": "Unable to retrieve payment method."}, status=400)

        card = pm.get("card") or {}
        brand = (card.get("brand") or "").strip()
        last4 = (card.get("last4") or "").strip()
        exp_month = card.get("exp_month")
        exp_year = card.get("exp_year")

        cs.stripe_payment_method_id = pm_id
        cs.stripe_payment_method_brand = brand
        cs.stripe_payment_method_last4 = last4
        cs.stripe_payment_method_exp_month = int(exp_month) if exp_month else None
        cs.stripe_payment_method_exp_year = int(exp_year) if exp_year else None
        cs.save(
            update_fields=[
                "stripe_payment_method_id",
                "stripe_payment_method_brand",
                "stripe_payment_method_last4",
                "stripe_payment_method_exp_month",
                "stripe_payment_method_exp_year",
            ]
        )

        return Response({"payment": _payment_payload(cs)})


class CustomerPaymentMethodAPIView(APIView):
    """
    GET /billing/customer/payment-method/
    Returns stored 'card on file' payload.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cs = _get_or_create_customer_settings(request.user)
        return Response({"payment": _payment_payload(cs)})


class CustomerRemoveCardAPIView(APIView):
    """
    POST /billing/customer/remove-card/
    Clears stored card metadata locally.
    (Does not delete in Stripe; does not detach payment method.)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        cs = _get_or_create_customer_settings(request.user)
        cs.stripe_payment_method_id = ""
        cs.stripe_payment_method_brand = ""
        cs.stripe_payment_method_last4 = ""
        cs.stripe_payment_method_exp_month = None
        cs.stripe_payment_method_exp_year = None
        cs.save(
            update_fields=[
                "stripe_payment_method_id",
                "stripe_payment_method_brand",
                "stripe_payment_method_last4",
                "stripe_payment_method_exp_month",
                "stripe_payment_method_exp_year",
            ]
        )
        return Response({"payment": _payment_payload(cs)})
