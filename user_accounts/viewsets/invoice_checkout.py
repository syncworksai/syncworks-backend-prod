from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import stripe
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Ticket, TicketMessage
from user_accounts.models.billing import Invoice


def _money_to_cents(v) -> int:
    try:
        amt = Decimal(str(v or "0"))
    except Exception:
        amt = Decimal("0.00")
    return int((amt * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _invoice_status_value(name: str, fallback: str) -> str:
    try:
        return getattr(Invoice.Status, name)
    except Exception:
        return fallback


def _payment_method_value(name: str, fallback: str) -> str:
    try:
        return getattr(Invoice.PaymentMethod, name)
    except Exception:
        return fallback


INVOICE_STATUS_DRAFT = _invoice_status_value("DRAFT", "DRAFT")
INVOICE_STATUS_SENT = _invoice_status_value("SENT", "SENT")
INVOICE_STATUS_PAID = _invoice_status_value("PAID", "PAID")
INVOICE_STATUS_VOID = _invoice_status_value("VOID", "VOID")

PAYMENT_METHOD_CARD = _payment_method_value("CARD", "CARD")


def _invoice_total_amount(invoice: Invoice) -> Decimal:
    try:
        return Decimal(str(invoice.total or "0.00"))
    except Exception:
        return Decimal("0.00")


def _build_success_url(invoice_id: int) -> str:
    base = (settings.PLATFORM_BASE_URL or "").rstrip("/")
    return f"{base}/customer/orders?paid=1&invoice_id={invoice_id}"


def _build_cancel_url(invoice_id: int) -> str:
    base = (settings.PLATFORM_BASE_URL or "").rstrip("/")
    return f"{base}/customer/orders?cancelled=1&invoice_id={invoice_id}"


def _user_can_pay_invoice(user, invoice: Invoice) -> bool:
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True

    ticket = getattr(invoice, "ticket", None)
    if not ticket:
        return False

    return getattr(ticket, "customer_id", None) == getattr(user, "id", None)


def _mark_invoice_and_ticket_paid(invoice: Invoice, *, payment_intent_id: str = "", charge_id: str = "") -> None:
    changed_invoice_fields: list[str] = []
    changed_ticket_fields: list[str] = []

    invoice.mark_paid(method=PAYMENT_METHOD_CARD)

    if payment_intent_id and getattr(invoice, "stripe_payment_intent_id", "") != payment_intent_id:
        invoice.stripe_payment_intent_id = payment_intent_id
        changed_invoice_fields.append("stripe_payment_intent_id")

    if charge_id and getattr(invoice, "stripe_charge_id", "") != charge_id:
        invoice.stripe_charge_id = charge_id
        changed_invoice_fields.append("stripe_charge_id")

    changed_invoice_fields.extend(
        [
            "status",
            "amount_paid",
            "paid_at",
            "platform_fee_amount",
            "platform_fee_collected",
            "platform_fee_collected_at",
        ]
    )

    if hasattr(invoice, "updated_at"):
        changed_invoice_fields.append("updated_at")

    dedup_invoice_fields: list[str] = []
    for f in changed_invoice_fields:
        if f not in dedup_invoice_fields:
            dedup_invoice_fields.append(f)

    invoice.save(update_fields=dedup_invoice_fields)

    ticket = getattr(invoice, "ticket", None)
    if ticket:
        ticket.status = Ticket.Status.PAID
        ticket.paid_at = timezone.now()
        changed_ticket_fields.extend(["status", "paid_at"])
        ticket.save(update_fields=changed_ticket_fields)

        try:
            TicketMessage.objects.create(
                ticket=ticket,
                sender=None,
                body=f"Invoice #{invoice.id} paid successfully.",
                type=TicketMessage.MessageType.SYSTEM,
            )
        except Exception:
            pass


def _resolve_invoice_from_checkout_session(session_obj) -> Invoice | None:
    metadata = session_obj.get("metadata") or {}
    invoice_id = metadata.get("invoice_id")

    if invoice_id:
        try:
            return Invoice.objects.filter(id=int(invoice_id)).first()
        except Exception:
            pass

    session_id = session_obj.get("id") or ""
    if session_id:
        try:
            return Invoice.objects.filter(stripe_checkout_session_id=session_id).first()
        except Exception:
            pass

    return None


def _resolve_invoice_from_payment_intent(pi_obj) -> Invoice | None:
    metadata = pi_obj.get("metadata") or {}
    invoice_id = metadata.get("invoice_id")

    if invoice_id:
        try:
            return Invoice.objects.filter(id=int(invoice_id)).first()
        except Exception:
            pass

    pi_id = pi_obj.get("id") or ""
    if pi_id:
        try:
            return Invoice.objects.filter(stripe_payment_intent_id=pi_id).first()
        except Exception:
            pass

    return None


class CreateInvoiceCheckoutSessionAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int):
        stripe.api_key = settings.STRIPE_SECRET_KEY

        invoice = get_object_or_404(Invoice, id=invoice_id)

        if not _user_can_pay_invoice(request.user, invoice):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        if invoice.status == INVOICE_STATUS_PAID:
            return Response(
                {"detail": "Invoice is already paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if invoice.status == INVOICE_STATUS_VOID:
            return Response(
                {"detail": "Invoice is void."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = _invoice_total_amount(invoice)
        amount_cents = _money_to_cents(amount)
        if amount_cents <= 0:
            return Response(
                {"detail": "Invoice total must be greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        title = (invoice.title or "").strip() or f"Invoice #{invoice.id}"
        notes = (invoice.notes or "").strip()

        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=_build_success_url(invoice.id),
            cancel_url=_build_cancel_url(invoice.id),
            payment_method_types=["card", "link"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": title,
                            "description": notes[:500] if notes else f"SyncWorks invoice #{invoice.id}",
                        },
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "invoice_id": str(invoice.id),
                "ticket_id": str(invoice.ticket_id or ""),
            },
            payment_intent_data={
                "metadata": {
                    "invoice_id": str(invoice.id),
                    "ticket_id": str(invoice.ticket_id or ""),
                }
            },
        )

        invoice.stripe_checkout_session_id = session.id
        save_fields = ["stripe_checkout_session_id"]
        if hasattr(invoice, "updated_at"):
            save_fields.append("updated_at")
        invoice.save(update_fields=save_fields)

        return Response(
            {
                "checkout_url": session.url,
                "session_id": session.id,
                "invoice_id": invoice.id,
            },
            status=status.HTTP_200_OK,
        )


class InvoicePaymentWebhookAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        stripe.api_key = settings.STRIPE_SECRET_KEY

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        webhook_secret = (
            getattr(settings, "STRIPE_INVOICE_WEBHOOK_SECRET", "") or getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        )
        if not webhook_secret:
            return Response({"detail": "Webhook secret is not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=webhook_secret,
            )
        except ValueError:
            return Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get("type") or ""
        data_object = (event.get("data") or {}).get("object") or {}

        try:
            with transaction.atomic():
                if event_type == "checkout.session.completed":
                    invoice = _resolve_invoice_from_checkout_session(data_object)
                    if invoice is None:
                        return Response({"ok": True, "ignored": "invoice_not_found"}, status=status.HTTP_200_OK)

                    payment_status = data_object.get("payment_status") or ""
                    payment_intent_id = data_object.get("payment_intent") or ""

                    changed_fields: list[str] = []

                    if payment_intent_id and getattr(invoice, "stripe_payment_intent_id", "") != payment_intent_id:
                        invoice.stripe_payment_intent_id = payment_intent_id
                        changed_fields.append("stripe_payment_intent_id")

                    session_id = data_object.get("id") or ""
                    if session_id and getattr(invoice, "stripe_checkout_session_id", "") != session_id:
                        invoice.stripe_checkout_session_id = session_id
                        changed_fields.append("stripe_checkout_session_id")

                    if changed_fields:
                        if hasattr(invoice, "updated_at"):
                            changed_fields.append("updated_at")
                        invoice.save(update_fields=changed_fields)

                    if payment_status == "paid":
                        _mark_invoice_and_ticket_paid(
                            invoice,
                            payment_intent_id=payment_intent_id,
                            charge_id="",
                        )

                elif event_type == "payment_intent.succeeded":
                    invoice = _resolve_invoice_from_payment_intent(data_object)
                    if invoice is None:
                        return Response({"ok": True, "ignored": "invoice_not_found"}, status=status.HTTP_200_OK)

                    payment_intent_id = data_object.get("id") or ""
                    latest_charge = data_object.get("latest_charge") or ""

                    _mark_invoice_and_ticket_paid(
                        invoice,
                        payment_intent_id=payment_intent_id,
                        charge_id=latest_charge,
                    )

                else:
                    return Response({"ok": True, "ignored": event_type}, status=status.HTTP_200_OK)

        except Exception as exc:
            return Response(
                {"detail": f"Webhook processing failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"ok": True}, status=status.HTTP_200_OK)