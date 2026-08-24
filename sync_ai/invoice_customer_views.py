from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Invoice, InvoiceEvent
from user_accounts.serializers.tickets import InvoiceSerializer


def _money(value, default="0.00") -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _derived_state(invoice: Invoice) -> str:
    paid = _money(invoice.amount_paid)
    total = _money(invoice.total)
    today = timezone.localdate()
    if invoice.status == Invoice.Status.VOID:
        return "VOID"
    if invoice.status == Invoice.Status.PAID or (total > 0 and paid >= total):
        return "PAID"
    if paid > 0:
        return "PARTIALLY_PAID"
    if invoice.status == Invoice.Status.SENT and invoice.due_date and invoice.due_date < today:
        return "OVERDUE"
    if invoice.status == Invoice.Status.SENT:
        return "SENT"
    return "DRAFT"


def _customer_queryset(user):
    return (
        Invoice.objects.select_related(
            "ticket",
            "ticket__assigned_business",
            "ticket__service_request",
        )
        .prefetch_related("line_items", "events")
        .filter(ticket__customer=user)
        .exclude(status=Invoice.Status.DRAFT)
        .order_by("-created_at")
    )


def _payload(invoice: Invoice, include_events=False):
    data = dict(InvoiceSerializer(invoice).data)
    ticket = invoice.ticket
    business = getattr(ticket, "assigned_business", None) if ticket else None
    balance = max(Decimal("0.00"), _money(invoice.total) - _money(invoice.amount_paid))
    data.update(
        {
            "derived_state": _derived_state(invoice),
            "balance_due": str(balance),
            "business_id": getattr(business, "id", None),
            "business_name": getattr(business, "name", "") or "Service provider",
            "ticket_code": getattr(ticket, "ticket_code", "") if ticket else "",
            "service_title": (
                getattr(ticket, "work_title", "")
                or getattr(getattr(ticket, "service_request", None), "title", "")
                or invoice.title
            ) if ticket else invoice.title,
            "can_pay": invoice.status not in {Invoice.Status.PAID, Invoice.Status.VOID} and balance > 0,
        }
    )
    if include_events:
        visible_types = {
            InvoiceEvent.EventType.CREATED,
            InvoiceEvent.EventType.SENT,
            InvoiceEvent.EventType.REMINDER,
            InvoiceEvent.EventType.PAYMENT_RECORDED,
            InvoiceEvent.EventType.PAID,
            InvoiceEvent.EventType.VOIDED,
        }
        data["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "message": event.message,
                "amount": str(event.amount) if event.amount is not None else None,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in invoice.events.all()
            if event.event_type in visible_types
        ]
    return data


class CustomerInvoiceCenterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        invoices = list(_customer_queryset(request.user))
        open_invoices = [i for i in invoices if _derived_state(i) not in {"PAID", "VOID"}]
        overdue = [i for i in invoices if _derived_state(i) == "OVERDUE"]
        outstanding = sum(
            (max(Decimal("0.00"), _money(i.total) - _money(i.amount_paid)) for i in open_invoices),
            Decimal("0.00"),
        )
        return Response(
            {
                "summary": {
                    "outstanding": str(outstanding.quantize(Decimal("0.01"))),
                    "open_count": len(open_invoices),
                    "overdue_count": len(overdue),
                    "paid_count": len([i for i in invoices if _derived_state(i) == "PAID"]),
                },
                "results": [_payload(invoice) for invoice in invoices],
            }
        )


class CustomerInvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, invoice_id: int):
        invoice = _customer_queryset(request.user).filter(pk=invoice_id).first()
        if not invoice:
            return Response({"detail": "Invoice not found."}, status=404)
        return Response(_payload(invoice, include_events=True))
