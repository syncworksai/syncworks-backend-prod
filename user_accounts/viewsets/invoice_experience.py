from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, Invoice, InvoiceEvent, Ticket
from user_accounts.serializers.tickets import InvoiceSerializer


CLOSED_INVOICE_STATUSES = {Invoice.Status.PAID, Invoice.Status.VOID}


def _money(value, default="0.00") -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _business_context(request):
    raw = request.headers.get("X-Business-Id") or request.headers.get("X-Business-ID") or request.query_params.get("business_id")
    try:
        business_id = int(raw) if raw else None
    except (TypeError, ValueError):
        business_id = None

    owned = Business.objects.filter(owner=request.user, is_active=True)
    memberships = BusinessMember.objects.filter(user=request.user, is_active=True, business__is_active=True).select_related("business")

    if business_id:
        business = Business.objects.filter(pk=business_id, is_active=True).first()
        if not business:
            raise LookupError("Business not found.")
        if business.owner_id == request.user.id:
            return business, None
        member = memberships.filter(business=business).first()
        if not member:
            raise PermissionError("You do not have access to this Business.")
        return business, member

    business = owned.order_by("id").first()
    if business:
        return business, None
    member = memberships.order_by("business_id").first()
    if member:
        return member.business, member
    raise LookupError("No active Business found.")


def _can_view_finance(business, member, user):
    if business.owner_id == user.id:
        return True
    return bool(member and (member.can_view_financials or member.can_manage_invoices))


def _can_manage_invoices(business, member, user):
    if business.owner_id == user.id:
        return True
    return bool(member and member.can_manage_invoices)


def _invoice_queryset(business):
    return (
        Invoice.objects.select_related("ticket", "ticket__customer", "ticket__service_request")
        .prefetch_related("line_items", "events")
        .filter(ticket__assigned_business=business)
        .order_by("-created_at")
    )


def _derived_state(invoice: Invoice):
    today = timezone.localdate()
    paid = _money(invoice.amount_paid)
    total = _money(invoice.total)
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


def _customer_name(ticket):
    if not ticket:
        return "Customer"
    customer = getattr(ticket, "customer", None)
    if customer:
        try:
            full = (customer.get_full_name() or "").strip()
            if full:
                return full
        except Exception:
            pass
        return getattr(customer, "email", "") or "Customer"
    return "Customer"


def _invoice_payload(invoice: Invoice, include_events=False):
    data = dict(InvoiceSerializer(invoice).data)
    ticket = invoice.ticket
    data.update({
        "derived_state": _derived_state(invoice),
        "balance_due": str(max(Decimal("0.00"), _money(invoice.total) - _money(invoice.amount_paid))),
        "ticket_code": getattr(ticket, "ticket_code", "") if ticket else "",
        "ticket_status": getattr(ticket, "status", "") if ticket else "",
        "customer_name": _customer_name(ticket),
        "marketplace_origin": bool(getattr(ticket, "is_marketplace", False)) if ticket else False,
        "service_title": (
            getattr(ticket, "work_title", "")
            or getattr(getattr(ticket, "service_request", None), "title", "")
            or invoice.title
        ) if ticket else invoice.title,
    })
    if include_events:
        data["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "message": event.message,
                "amount": str(event.amount) if event.amount is not None else None,
                "payment_source": event.payment_source,
                "external_reference": event.external_reference,
                "occurred_at": event.occurred_at.isoformat(),
                "actor_id": event.actor_id,
            }
            for event in invoice.events.all()
        ]
    return data


def _get_invoice(business, invoice_id):
    invoice = _invoice_queryset(business).filter(pk=invoice_id).first()
    if not invoice:
        raise LookupError("Invoice not found for this Business.")
    return invoice


class BusinessInvoiceCenterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _business_context(request)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_view_finance(business, member, request.user):
            return Response({"detail": "Financial access required."}, status=403)

        invoices = list(_invoice_queryset(business))
        state = str(request.query_params.get("state") or "").strip().upper()
        if state:
            invoices = [invoice for invoice in invoices if _derived_state(invoice) == state]

        today = timezone.localdate()
        month_start = today.replace(day=1)
        all_invoices = list(_invoice_queryset(business))
        outstanding = sum((max(Decimal("0.00"), _money(i.total) - _money(i.amount_paid)) for i in all_invoices if i.status not in CLOSED_INVOICE_STATUSES), Decimal("0.00"))
        overdue = [i for i in all_invoices if _derived_state(i) == "OVERDUE"]
        due_soon = [i for i in all_invoices if i.status == Invoice.Status.SENT and i.due_date and today <= i.due_date <= today + timedelta(days=7)]
        paid_month = sum((_money(i.amount_paid) for i in all_invoices if i.paid_at and i.paid_at.date() >= month_start), Decimal("0.00"))

        invoiced_ticket_ids = {i.ticket_id for i in all_invoices if i.ticket_id and i.status != Invoice.Status.VOID}
        ready_tickets = list(
            Ticket.objects.select_related("customer", "service_request")
            .filter(assigned_business=business, status=Ticket.Status.COMPLETED)
            .exclude(id__in=invoiced_ticket_ids)
            .order_by("-created_at")[:50]
        )

        suggestions = []
        if ready_tickets:
            suggestions.append({"type": "READY_TO_BILL", "count": len(ready_tickets), "message": f"{len(ready_tickets)} completed job(s) are ready to invoice."})
        if overdue:
            suggestions.append({"type": "OVERDUE", "count": len(overdue), "message": f"{len(overdue)} invoice(s) are overdue and need follow-up."})
        if due_soon:
            suggestions.append({"type": "DUE_SOON", "count": len(due_soon), "message": f"{len(due_soon)} invoice(s) are due in the next 7 days."})

        return Response({
            "business_id": business.id,
            "business_name": business.name,
            "summary": {
                "invoice_count": len(all_invoices),
                "outstanding": str(outstanding.quantize(Decimal("0.01"))),
                "overdue_count": len(overdue),
                "due_soon_count": len(due_soon),
                "paid_this_month": str(paid_month.quantize(Decimal("0.01"))),
                "ready_to_bill_count": len(ready_tickets),
            },
            "suggestions": suggestions,
            "ready_to_bill": [
                {
                    "ticket_id": ticket.id,
                    "ticket_code": ticket.ticket_code,
                    "title": ticket.work_title or getattr(ticket.service_request, "title", "") or "Completed job",
                    "customer_name": _customer_name(ticket),
                    "marketplace_origin": bool(ticket.is_marketplace),
                    "total_amount_cents": ticket.total_amount_cents,
                }
                for ticket in ready_tickets
            ],
            "results": [_invoice_payload(invoice) for invoice in invoices],
        })


class BusinessInvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, invoice_id: int):
        try:
            business, member = _business_context(request)
            invoice = _get_invoice(business, invoice_id)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_view_finance(business, member, request.user):
            return Response({"detail": "Financial access required."}, status=403)
        return Response(_invoice_payload(invoice, include_events=True))


class BusinessInvoiceFromTicketView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, ticket_id: int):
        try:
            business, member = _business_context(request)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage_invoices(business, member, request.user):
            return Response({"detail": "Invoice management permission required."}, status=403)

        ticket = Ticket.objects.select_related("customer", "service_request").filter(pk=ticket_id, assigned_business=business).first()
        if not ticket:
            return Response({"detail": "Ticket not found for this Business."}, status=404)
        existing = Invoice.objects.filter(ticket=ticket).exclude(status=Invoice.Status.VOID).order_by("-created_at").first()
        if existing:
            return Response(_invoice_payload(existing, include_events=True), status=200)

        cents = int(ticket.total_amount_cents or 0)
        total = (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
        title = str(request.data.get("title") or ticket.work_title or getattr(ticket.service_request, "title", "") or f"Service invoice #{ticket.id}")
        due_days = request.data.get("due_days", 14)
        try:
            due_days = max(0, min(120, int(due_days)))
        except (TypeError, ValueError):
            due_days = 14
        invoice = Invoice.objects.create(
            ticket=ticket,
            title=title,
            notes=str(request.data.get("notes") or ""),
            subtotal=total,
            tax=Decimal("0.00"),
            total=total,
            due_date=timezone.localdate() + timedelta(days=due_days),
            payment_method=Invoice.PaymentMethod.CARD,
        )
        InvoiceEvent.objects.create(invoice=invoice, event_type=InvoiceEvent.EventType.CREATED, actor=request.user, message="Invoice draft created from completed job.")
        return Response(_invoice_payload(invoice, include_events=True), status=201)


class BusinessInvoiceActionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, invoice_id: int, action_name: str):
        try:
            business, member = _business_context(request)
            invoice = _get_invoice(business, invoice_id)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage_invoices(business, member, request.user):
            return Response({"detail": "Invoice management permission required."}, status=403)

        action_name = str(action_name or "").lower()
        if action_name == "send":
            if invoice.status == Invoice.Status.VOID:
                return Response({"detail": "A void invoice cannot be sent."}, status=409)
            invoice.status = Invoice.Status.SENT
            invoice.save(update_fields=["status", "updated_at"])
            if invoice.ticket_id and invoice.ticket:
                ticket = invoice.ticket
                if not ticket.invoiced_at:
                    ticket.invoiced_at = timezone.now()
                    ticket.save(update_fields=["invoiced_at"])
            InvoiceEvent.objects.create(invoice=invoice, event_type=InvoiceEvent.EventType.SENT, actor=request.user, message="Invoice marked sent to customer.")

        elif action_name == "reminder":
            if invoice.status != Invoice.Status.SENT:
                return Response({"detail": "Only sent invoices can receive a payment reminder."}, status=409)
            InvoiceEvent.objects.create(invoice=invoice, event_type=InvoiceEvent.EventType.REMINDER, actor=request.user, message="Payment reminder queued from Invoice Center.")

        elif action_name == "void":
            if invoice.status == Invoice.Status.PAID:
                return Response({"detail": "Paid invoices must be reconciled, not voided."}, status=409)
            invoice.status = Invoice.Status.VOID
            invoice.save(update_fields=["status", "updated_at"])
            InvoiceEvent.objects.create(invoice=invoice, event_type=InvoiceEvent.EventType.VOIDED, actor=request.user, message=str(request.data.get("reason") or "Invoice voided."))

        elif action_name == "record-payment":
            if invoice.status == Invoice.Status.VOID:
                return Response({"detail": "Cannot record payment on a void invoice."}, status=409)
            amount = _money(request.data.get("amount"))
            if amount <= 0:
                return Response({"detail": "Payment amount must be greater than zero."}, status=400)
            source = str(request.data.get("source") or "OTHER").upper()
            reference = str(request.data.get("reference") or "")[:255]
            new_paid = min(_money(invoice.total), _money(invoice.amount_paid) + amount)
            invoice.amount_paid = new_paid
            fully_paid = _money(invoice.total) > 0 and new_paid >= _money(invoice.total)
            if fully_paid:
                method = Invoice.PaymentMethod.CASH if source == "CASH" else Invoice.PaymentMethod.OTHER
                if source == "SYNC_CARD":
                    method = Invoice.PaymentMethod.CARD
                invoice.mark_paid(method=method)
                if source != "SYNC_CARD":
                    invoice.platform_fee_collected = False
                    invoice.platform_fee_collected_at = None
            else:
                invoice.status = Invoice.Status.SENT
            invoice.save()
            InvoiceEvent.objects.create(
                invoice=invoice,
                event_type=InvoiceEvent.EventType.PAID if fully_paid else InvoiceEvent.EventType.PAYMENT_RECORDED,
                actor=request.user,
                message="Payment recorded in SyncWorks." if source == "SYNC_CARD" else "External payment recorded for reconciliation; SyncWorks did not process this payment.",
                amount=amount,
                payment_source=source,
                external_reference=reference,
            )
        else:
            return Response({"detail": "Unknown invoice action."}, status=404)

        invoice.refresh_from_db()
        return Response(_invoice_payload(invoice, include_events=True))
