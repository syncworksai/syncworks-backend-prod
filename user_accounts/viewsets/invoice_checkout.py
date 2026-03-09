# backend/user_accounts/viewsets/invoice_checkout.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Tuple

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, Invoice


def _stripe_key() -> str:
    return (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()


def _invoice_webhook_secret() -> str:
    # You can set a dedicated secret for invoice payments webhook
    # STRIPE_INVOICE_WEBHOOK_SECRET=whsec_...
    # If not set, fallback to STRIPE_WEBHOOK_SECRET.
    return (
        (getattr(settings, "STRIPE_INVOICE_WEBHOOK_SECRET", "") or "").strip()
        or (getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip()
    )


def _base_url() -> str:
    return (getattr(settings, "PLATFORM_BASE_URL", "") or "").rstrip("/") or "http://localhost:5174"


def _money_to_cents(amount: Any) -> int:
    if amount is None:
        return 0
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _cents_to_money(cents: int) -> Decimal:
    return (Decimal(int(cents)) / Decimal("100")).quantize(Decimal("0.01"))


def _is_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or getattr(user, "is_platform_admin", False)
    )


def _safe_setattr(obj, field: str, value) -> bool:
    """Set attribute only if it exists. Returns True if set."""
    if hasattr(obj, field):
        setattr(obj, field, value)
        return True
    return False


def _safe_update_fields(fields: list[str]) -> list[str]:
    """De-duplicate update_fields while preserving order."""
    seen = set()
    out: list[str] = []
    for f in fields:
        if f and f not in seen:
            out.append(f)
            seen.add(f)
    return out


def _invoice_amount_cents(inv: Invoice) -> int:
    """
    Your current Invoice model (as shown) has amount_cents.
    Some earlier drafts used inv.total (Decimal dollars). Support both safely.
    """
    if hasattr(inv, "amount_cents") and inv.amount_cents is not None:
        try:
            return int(inv.amount_cents)
        except Exception:
            pass

    # fallback: inv.total dollars -> cents (if you later add it)
    if hasattr(inv, "total") and getattr(inv, "total", None) is not None:
        return _money_to_cents(getattr(inv, "total"))

    return 0


def _platform_fee_cents(total_cents: int, fee_bps: int) -> int:
    """
    fee_bps: basis points (100 = 1%)
    """
    fee_cents = int(
        (Decimal(total_cents) * Decimal(int(fee_bps)) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    if fee_cents < 0:
        fee_cents = 0
    if fee_cents > total_cents:
        fee_cents = total_cents
    return fee_cents


def _destination_account_for_invoice(inv: Invoice) -> Tuple[str | None, Response | None]:
    """
    For JOB invoices tied to Stripe Connect payouts:
    - If you later add inv.ticket -> inv.ticket.assigned_business_id, use that.
    - For now, we use inv.business.stripe_connect_account_id (works for your current model).
    """
    biz = getattr(inv, "business", None)
    if not biz:
        return None, Response({"detail": "Invoice has no business."}, status=400)

    acct = (getattr(biz, "stripe_connect_account_id", "") or "").strip()
    if not acct:
        return None, Response(
            {"detail": "Business is not connected to Stripe yet (missing stripe_connect_account_id)."},
            status=400,
        )

    return acct, None


class CreateInvoiceCheckoutSessionAPIView(APIView):
    """
    POST /billing/invoices/<invoice_id>/checkout/

    Creates a Stripe Checkout session (mode=payment) that:
      - charges customer on PLATFORM account
      - takes 1% platform fee (application_fee_amount)
      - transfers remainder to connected account (transfer_data[destination])

    NOTE:
    - Your current Invoice model does NOT have ticket linkage yet.
    - We base amount on Invoice.amount_cents.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int):
        if not _stripe_key():
            return Response({"detail": "Stripe not configured (missing STRIPE_SECRET_KEY)."}, status=500)

        inv = Invoice.objects.filter(id=invoice_id).select_related("business").first()
        if not inv:
            return Response({"detail": "Invoice not found."}, status=404)

        # Admin bypass for testing / platform ops
        if not _is_admin(request.user):
            # If later you want to restrict: customer/owner checks go here.
            pass

        # must be payable
        if str(inv.status) in ("PAID", "VOID"):
            return Response({"detail": f"Invoice cannot be paid in status={inv.status}."}, status=400)

        destination_acct, derr = _destination_account_for_invoice(inv)
        if derr:
            return derr

        total_cents = _invoice_amount_cents(inv)
        if total_cents <= 0:
            return Response({"detail": "Invoice amount must be greater than $0.00."}, status=400)

        fee_rate_bps = int(getattr(inv, "platform_fee_rate_bps", 100) or 100)  # default 1%
        fee_cents = _platform_fee_cents(total_cents, fee_rate_bps)

        stripe.api_key = _stripe_key()

        base = _base_url()
        success_url = f"{base}/customer/orders?paid=1&invoice_id={inv.id}&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/customer/orders?cancelled=1&invoice_id={inv.id}"

        # Helpful labels
        invoice_name = (getattr(inv, "title", "") or "").strip() or f"Service Invoice #{inv.id}"
        invoice_desc = (getattr(inv, "notes", "") or "").strip()
        if invoice_desc:
            invoice_desc = invoice_desc[:500]
        else:
            invoice_desc = None

        # Metadata used by webhook to reconcile
        business_id = str(getattr(inv, "business_id", "") or "")

        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": total_cents,
                            "product_data": {
                                "name": invoice_name,
                                **({"description": invoice_desc} if invoice_desc else {}),
                            },
                        },
                    }
                ],
                success_url=success_url,
                cancel_url=cancel_url,
                payment_intent_data={
                    "application_fee_amount": fee_cents,
                    "transfer_data": {"destination": destination_acct},
                    "metadata": {
                        "kind": "invoice_payment",
                        "invoice_id": str(inv.id),
                        "business_id": business_id,
                        "platform_fee_bps": str(fee_rate_bps),
                    },
                },
                metadata={
                    "kind": "invoice_payment",
                    "invoice_id": str(inv.id),
                    "business_id": business_id,
                },
                client_reference_id=str(inv.id),
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error creating Checkout Session.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error creating Checkout Session.", "error": str(e)}, status=500)

        # Store checkout session id/url if the fields exist
        update_fields: list[str] = []
        if _safe_setattr(inv, "stripe_checkout_session_id", session.get("id") or ""):
            update_fields.append("stripe_checkout_session_id")
        if _safe_setattr(inv, "stripe_checkout_url", session.get("url") or ""):
            update_fields.append("stripe_checkout_url")

        # Optional updated_at if present
        if hasattr(inv, "updated_at"):
            inv.updated_at = timezone.now()
            update_fields.append("updated_at")

        if update_fields:
            inv.save(update_fields=_safe_update_fields(update_fields))

        return Response({"url": session.get("url"), "session_id": session.get("id"), "fee_cents": fee_cents})


class InvoicePaymentWebhookAPIView(APIView):
    """
    POST /billing/invoices/webhook/

    Stripe webhook for invoice checkout.
    Marks Invoice.status=PAID when Stripe confirms payment.

    Handles:
      - checkout.session.completed (recommended)
      - payment_intent.succeeded (backup)

    IMPORTANT:
      - set STRIPE_INVOICE_WEBHOOK_SECRET (or STRIPE_WEBHOOK_SECRET fallback)
      - stripe listen --forward-to http://127.0.0.1:8000/api/v1/billing/invoices/webhook/
    """
    permission_classes = [AllowAny]
    authentication_classes: list = []  # Stripe posts without auth

    def post(self, request):
        if not _stripe_key():
            return Response({"detail": "Stripe not configured."}, status=500)

        secret = _invoice_webhook_secret()
        if not secret:
            return Response(
                {"detail": "Webhook secret not configured (missing STRIPE_INVOICE_WEBHOOK_SECRET/STRIPE_WEBHOOK_SECRET)."},
                status=500,
            )

        stripe.api_key = _stripe_key()

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=secret)
        except ValueError:
            return Response({"detail": "Invalid payload."}, status=400)
        except stripe.error.SignatureVerificationError:
            return Response({"detail": "Invalid signature."}, status=400)

        etype = event.get("type") or ""
        obj = (event.get("data") or {}).get("object") or {}

        def _extract_invoice_id() -> int | None:
            md = obj.get("metadata") or {}
            if md.get("invoice_id"):
                try:
                    return int(md.get("invoice_id"))
                except Exception:
                    pass

            if obj.get("client_reference_id"):
                try:
                    return int(obj.get("client_reference_id"))
                except Exception:
                    pass

            return None

        invoice_id = _extract_invoice_id()
        if not invoice_id:
            return Response({"received": True, "ignored": True, "reason": "missing invoice_id"}, status=200)

        paid = False
        amount_total_cents: int | None = None
        payment_intent_id: str | None = None

        if etype == "checkout.session.completed":
            paid = (obj.get("payment_status") == "paid") or bool(obj.get("paid"))
            amount_total_cents = obj.get("amount_total")
            payment_intent_id = obj.get("payment_intent")
        elif etype == "payment_intent.succeeded":
            paid = True
            amount_total_cents = obj.get("amount_received") or obj.get("amount")
            payment_intent_id = obj.get("id")

        if not paid:
            return Response({"received": True, "ignored": True, "reason": f"event {etype} not paid"}, status=200)

        with transaction.atomic():
            inv = Invoice.objects.select_for_update().filter(id=invoice_id).first()
            if not inv:
                return Response({"received": True, "ignored": True, "reason": "invoice not found"}, status=200)

            if str(inv.status) == "PAID":
                return Response({"received": True, "ok": True, "already_paid": True}, status=200)

            now = timezone.now()
            inv.status = "PAID"
            inv.paid_at = now

            update_fields: list[str] = ["status", "paid_at"]

            # Optional amount_paid (if you add it later)
            if hasattr(inv, "amount_paid"):
                if amount_total_cents is not None:
                    inv.amount_paid = _cents_to_money(int(amount_total_cents))
                update_fields.append("amount_paid")

            # Optional updated_at
            if hasattr(inv, "updated_at"):
                inv.updated_at = now
                update_fields.append("updated_at")

            # Optional stripe_payment_intent_id
            if payment_intent_id and hasattr(inv, "stripe_payment_intent_id"):
                inv.stripe_payment_intent_id = payment_intent_id
                update_fields.append("stripe_payment_intent_id")

            inv.save(update_fields=_safe_update_fields(update_fields))

        return Response({"received": True, "ok": True}, status=200)