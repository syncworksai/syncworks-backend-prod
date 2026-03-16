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

from user_accounts.models import Business
from user_accounts.models.billing import Invoice


def _stripe_key() -> str:
    return (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()


def _invoice_webhook_secret() -> str:
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
    if hasattr(obj, field):
        setattr(obj, field, value)
        return True
    return False


def _safe_update_fields(fields: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for f in fields:
        if f and f not in seen:
            out.append(f)
            seen.add(f)
    return out


def _invoice_amount_cents(inv: Invoice) -> int:
    if hasattr(inv, "total") and getattr(inv, "total", None) is not None:
        return _money_to_cents(getattr(inv, "total"))

    if hasattr(inv, "amount_cents") and inv.amount_cents is not None:
        try:
            return int(inv.amount_cents)
        except Exception:
            pass

    return 0


def _platform_fee_cents(total_cents: int, fee_bps: int) -> int:
    fee_cents = int(
        (Decimal(total_cents) * Decimal(int(fee_bps)) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    if fee_cents < 0:
        fee_cents = 0
    if fee_cents > total_cents:
        fee_cents = total_cents
    return fee_cents


def _destination_account_for_invoice(inv: Invoice) -> Tuple[str | None, Response | None]:
    ticket = getattr(inv, "ticket", None)
    if not ticket:
        return None, Response({"detail": "Invoice has no linked ticket."}, status=400)

    biz = getattr(ticket, "assigned_business", None)
    if not biz:
        return None, Response({"detail": "Invoice ticket has no assigned business."}, status=400)

    acct = (getattr(biz, "stripe_connect_account_id", "") or "").strip()
    if not acct:
        return None, Response(
            {"detail": "Business is not connected to Stripe yet (missing stripe_connect_account_id)."},
            status=400,
        )

    return acct, None


class CreateInvoiceCheckoutSessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int):
        if not _stripe_key():
            return Response({"detail": "Stripe not configured (missing STRIPE_SECRET_KEY)."}, status=500)

        inv = (
            Invoice.objects.filter(id=invoice_id)
            .select_related("ticket", "ticket__customer", "ticket__assigned_business")
            .first()
        )
        if not inv:
            return Response({"detail": "Invoice not found."}, status=404)

        if not _is_admin(request.user):
            ticket = getattr(inv, "ticket", None)
            if not ticket or int(getattr(ticket, "customer_id", 0) or 0) != int(request.user.id):
                return Response({"detail": "Not allowed."}, status=403)

        if str(inv.status) in ("PAID", "VOID"):
            return Response({"detail": f"Invoice cannot be paid in status={inv.status}."}, status=400)

        destination_acct, derr = _destination_account_for_invoice(inv)
        if derr:
            return derr

        total_cents = _invoice_amount_cents(inv)
        if total_cents <= 0:
            return Response({"detail": "Invoice amount must be greater than $0.00."}, status=400)

        fee_rate_bps = int(getattr(inv, "platform_fee_rate_bps", 100) or 100)
        fee_cents = _platform_fee_cents(total_cents, fee_rate_bps)

        stripe.api_key = _stripe_key()

        base = _base_url()
        success_url = f"{base}/customer/orders?paid=1&invoice_id={inv.id}&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/customer/orders?cancelled=1&invoice_id={inv.id}"

        invoice_name = (getattr(inv, "title", "") or "").strip() or f"Service Invoice #{inv.id}"
        invoice_desc = (getattr(inv, "notes", "") or "").strip()
        if invoice_desc:
            invoice_desc = invoice_desc[:500]
        else:
            invoice_desc = None

        ticket = getattr(inv, "ticket", None)
        assigned_business = getattr(ticket, "assigned_business", None) if ticket else None
        business_id = str(getattr(assigned_business, "id", "") or "")
        ticket_id = str(getattr(ticket, "id", "") or "")

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
                        "ticket_id": ticket_id,
                        "business_id": business_id,
                        "platform_fee_bps": str(fee_rate_bps),
                    },
                },
                metadata={
                    "kind": "invoice_payment",
                    "invoice_id": str(inv.id),
                    "ticket_id": ticket_id,
                    "business_id": business_id,
                },
                client_reference_id=str(inv.id),
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error creating Checkout Session.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error creating Checkout Session.", "error": str(e)}, status=500)

        update_fields: list[str] = []
        if _safe_setattr(inv, "stripe_checkout_session_id", session.get("id") or ""):
            update_fields.append("stripe_checkout_session_id")
        if _safe_setattr(inv, "stripe_checkout_url", session.get("url") or ""):
            update_fields.append("stripe_checkout_url")
        if hasattr(inv, "updated_at"):
            inv.updated_at = timezone.now()
            update_fields.append("updated_at")

        if update_fields:
            inv.save(update_fields=_safe_update_fields(update_fields))

        return Response({"url": session.get("url"), "session_id": session.get("id"), "fee_cents": fee_cents})


class InvoicePaymentWebhookAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

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

            if hasattr(inv, "amount_paid") and amount_total_cents is not None:
                inv.amount_paid = _cents_to_money(int(amount_total_cents))
                update_fields.append("amount_paid")

            if hasattr(inv, "updated_at"):
                inv.updated_at = now
                update_fields.append("updated_at")

            if payment_intent_id and hasattr(inv, "stripe_payment_intent_id"):
                inv.stripe_payment_intent_id = payment_intent_id
                update_fields.append("stripe_payment_intent_id")

            try:
                if hasattr(inv, "mark_platform_fee_collected") and getattr(inv, "payment_method", "") == "CARD":
                    inv.mark_platform_fee_collected()
                    if "platform_fee_collected" not in update_fields:
                        update_fields.append("platform_fee_collected")
                    if hasattr(inv, "platform_fee_collected_at") and "platform_fee_collected_at" not in update_fields:
                        update_fields.append("platform_fee_collected_at")
            except Exception:
                pass

            inv.save(update_fields=_safe_update_fields(update_fields))

            ticket = getattr(inv, "ticket", None)
            if ticket and hasattr(ticket, "status"):
                try:
                    ticket.status = ticket.Status.PAID
                    ticket.paid_at = now
                    ticket.save(update_fields=["status", "paid_at"])
                except Exception:
                    pass

        return Response({"received": True, "ok": True}, status=200)
