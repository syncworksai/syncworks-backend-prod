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

from platform_affiliates.services.invoice_commission_service import record_invoice_platform_fee_commission
from user_accounts.models import InvoiceEvent, Notification, Ticket, TicketMessage
from user_accounts.models.billing import Invoice


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or "0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _money_to_cents(value) -> int:
    return int((_money(value) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def _invoice_balance(invoice: Invoice) -> Decimal:
    return max(Decimal("0.00"), _money(invoice.total) - _money(invoice.amount_paid))


def _build_success_url(invoice_id: int) -> str:
    base = (settings.PLATFORM_BASE_URL or "").rstrip("/")
    return f"{base}/customer/invoices?paid=1&invoice_id={invoice_id}"


def _build_cancel_url(invoice_id: int) -> str:
    base = (settings.PLATFORM_BASE_URL or "").rstrip("/")
    return f"{base}/customer/invoices?cancelled=1&invoice_id={invoice_id}"


def _user_can_pay_invoice(user, invoice: Invoice) -> bool:
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    ticket = getattr(invoice, "ticket", None)
    return bool(ticket and getattr(ticket, "customer_id", None) == getattr(user, "id", None))


def _notify_paid(invoice: Invoice) -> None:
    ticket = getattr(invoice, "ticket", None)
    customer = getattr(ticket, "customer", None) if ticket else None
    if not customer:
        return
    exists = Notification.objects.filter(
        recipient=customer,
        type=Notification.TYPE_BILLING,
        data__invoice_id=invoice.id,
        data__event="INVOICE_PAID",
    ).exists()
    if not exists:
        Notification.objects.create(
            recipient=customer,
            type=Notification.TYPE_BILLING,
            title=f"Payment complete · Invoice #{invoice.id}",
            body=f"Your payment of ${_money(invoice.total)} was received successfully.",
            data={
                "invoice_id": invoice.id,
                "ticket_id": invoice.ticket_id,
                "event": "INVOICE_PAID",
                "route": f"/customer/invoices?invoice_id={invoice.id}",
            },
        )


def _mark_invoice_and_ticket_paid(invoice: Invoice, *, payment_intent_id: str = "", charge_id: str = "") -> None:
    already_paid = invoice.status == INVOICE_STATUS_PAID
    invoice.mark_paid(method=PAYMENT_METHOD_CARD)
    changed_fields = [
        "status",
        "amount_paid",
        "paid_at",
        "platform_fee_amount",
        "platform_fee_collected",
        "platform_fee_collected_at",
    ]
    if payment_intent_id and invoice.stripe_payment_intent_id != payment_intent_id:
        invoice.stripe_payment_intent_id = payment_intent_id
        changed_fields.append("stripe_payment_intent_id")
    if charge_id and invoice.stripe_charge_id != charge_id:
        invoice.stripe_charge_id = charge_id
        changed_fields.append("stripe_charge_id")
    if hasattr(invoice, "updated_at"):
        changed_fields.append("updated_at")
    invoice.save(update_fields=list(dict.fromkeys(changed_fields)))

    record_invoice_platform_fee_commission(invoice)

    ticket = getattr(invoice, "ticket", None)
    if ticket:
        ticket.status = Ticket.Status.PAID
        ticket.paid_at = invoice.paid_at or timezone.now()
        ticket.save(update_fields=["status", "paid_at"])
        if not already_paid:
            TicketMessage.objects.create(
                ticket=ticket,
                sender=None,
                body=f"Invoice #{invoice.id} paid successfully through SyncWorks.",
                type=TicketMessage.MessageType.SYSTEM,
            )

    if not already_paid:
        InvoiceEvent.objects.create(
            invoice=invoice,
            event_type=InvoiceEvent.EventType.PAID,
            message="Invoice paid through SyncWorks checkout.",
            amount=_money(invoice.total),
            payment_source="SYNC_CARD",
            external_reference=payment_intent_id or charge_id,
        )
    _notify_paid(invoice)


def _resolve_invoice_from_checkout_session(session_obj) -> Invoice | None:
    metadata = session_obj.get("metadata") or {}
    invoice_id = metadata.get("invoice_id")
    if invoice_id:
        try:
            return Invoice.objects.filter(id=int(invoice_id)).first()
        except Exception:
            pass
    session_id = session_obj.get("id") or ""
    return Invoice.objects.filter(stripe_checkout_session_id=session_id).first() if session_id else None


def _resolve_invoice_from_payment_intent(pi_obj) -> Invoice | None:
    metadata = pi_obj.get("metadata") or {}
    invoice_id = metadata.get("invoice_id")
    if invoice_id:
        try:
            return Invoice.objects.filter(id=int(invoice_id)).first()
        except Exception:
            pass
    pi_id = pi_obj.get("id") or ""
    return Invoice.objects.filter(stripe_payment_intent_id=pi_id).first() if pi_id else None


class CreateInvoiceCheckoutSessionAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        invoice = get_object_or_404(Invoice.objects.select_related("ticket", "ticket__customer"), id=invoice_id)

        if not _user_can_pay_invoice(request.user, invoice):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if invoice.status == INVOICE_STATUS_PAID:
            return Response({"detail": "Invoice is already paid."}, status=status.HTTP_400_BAD_REQUEST)
        if invoice.status == INVOICE_STATUS_VOID:
            return Response({"detail": "Invoice is void."}, status=status.HTTP_400_BAD_REQUEST)
        if invoice.status == INVOICE_STATUS_DRAFT:
            return Response({"detail": "Invoice has not been sent yet."}, status=status.HTTP_409_CONFLICT)

        balance = _invoice_balance(invoice)
        amount_cents = _money_to_cents(balance)
        if amount_cents <= 0:
            return Response({"detail": "No balance remains on this invoice."}, status=status.HTTP_400_BAD_REQUEST)

        title = (invoice.title or "").strip() or f"Invoice #{invoice.id}"
        notes = (invoice.notes or "").strip()
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                success_url=_build_success_url(invoice.id),
                cancel_url=_build_cancel_url(invoice.id),
                payment_method_types=["card", "link"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": title,
                            "description": notes[:500] if notes else f"SyncWorks invoice #{invoice.id}",
                        },
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }],
                metadata={
                    "invoice_id": str(invoice.id),
                    "ticket_id": str(invoice.ticket_id or ""),
                    "balance_cents": str(amount_cents),
                },
                payment_intent_data={
                    "metadata": {
                        "invoice_id": str(invoice.id),
                        "ticket_id": str(invoice.ticket_id or ""),
                        "balance_cents": str(amount_cents),
                    }
                },
            )
        except Exception as exc:
            return Response({"detail": f"Stripe checkout session creation failed: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        invoice.stripe_checkout_session_id = session.id
        invoice.save(update_fields=["stripe_checkout_session_id", "updated_at"])
        InvoiceEvent.objects.create(
            invoice=invoice,
            event_type=InvoiceEvent.EventType.PAYMENT_RECORDED,
            actor=request.user,
            message="Customer opened SyncWorks checkout.",
            amount=balance,
            payment_source="SYNC_CHECKOUT_STARTED",
            external_reference=session.id,
        )
        return Response({
            "checkout_url": session.url,
            "session_id": session.id,
            "invoice_id": invoice.id,
            "amount_due": str(balance),
        })


class InvoicePaymentWebhookAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        webhook_secret = getattr(settings, "STRIPE_INVOICE_WEBHOOK_SECRET", "") or getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        if not webhook_secret:
            return Response({"detail": "Webhook secret is not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=webhook_secret)
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
                        return Response({"ok": True, "ignored": "invoice_not_found"})
                    payment_intent_id = data_object.get("payment_intent") or ""
                    changed_fields = []
                    session_id = data_object.get("id") or ""
                    if session_id and invoice.stripe_checkout_session_id != session_id:
                        invoice.stripe_checkout_session_id = session_id
                        changed_fields.append("stripe_checkout_session_id")
                    if payment_intent_id and invoice.stripe_payment_intent_id != payment_intent_id:
                        invoice.stripe_payment_intent_id = payment_intent_id
                        changed_fields.append("stripe_payment_intent_id")
                    if changed_fields:
                        changed_fields.append("updated_at")
                        invoice.save(update_fields=changed_fields)
                    if (data_object.get("payment_status") or "") == "paid":
                        _mark_invoice_and_ticket_paid(invoice, payment_intent_id=payment_intent_id)

                elif event_type == "payment_intent.succeeded":
                    invoice = _resolve_invoice_from_payment_intent(data_object)
                    if invoice is None:
                        return Response({"ok": True, "ignored": "invoice_not_found"})
                    _mark_invoice_and_ticket_paid(
                        invoice,
                        payment_intent_id=data_object.get("id") or "",
                        charge_id=data_object.get("latest_charge") or "",
                    )
                else:
                    return Response({"ok": True, "ignored": event_type})
        except Exception as exc:
            return Response({"detail": f"Webhook processing failed: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"ok": True})
