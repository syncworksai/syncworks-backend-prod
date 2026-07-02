from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    Invoice,
    PartnerInvoice,
    PartnerPayment,
    PartnerPaymentAllocation,
    PartnerWorkTicket,
    Ticket,
)
from user_accounts.serializers.partner_billing import (
    PartnerInvoiceSerializer,
    PartnerPaymentSerializer,
)
from user_accounts.viewsets.ticket_conversations import _business_context


AUTO_CONFIRM_METHODS = {
    PartnerPayment.Method.CREDIT_CARD,
    PartnerPayment.Method.DEBIT_CARD,
    PartnerPayment.Method.ACH,
    PartnerPayment.Method.STRIPE,
}


def _whole_cents(value, field_name: str, allow_zero: bool = True) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        raise ValidationError({field_name: "Use a whole number of cents."})
    if parsed < 0 or (not allow_zero and parsed == 0):
        raise ValidationError(
            {field_name: "Amount must be greater than zero."}
        )
    return parsed


def _line_items(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError({"line_items": "Use a list of line items."})
    cleaned = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValidationError(
                {"line_items": f"Item {index + 1} must be an object."}
            )
        description = str(
            item.get("description") or item.get("name") or ""
        ).strip()
        quantity = item.get("quantity", 1)
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            raise ValidationError(
                {"line_items": f"Item {index + 1} quantity is invalid."}
            )
        if quantity < 0:
            raise ValidationError(
                {"line_items": f"Item {index + 1} quantity cannot be negative."}
            )
        unit_amount = _whole_cents(
            item.get("unit_amount_cents", 0),
            f"line_items[{index}].unit_amount_cents",
        )
        cleaned.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_amount_cents": unit_amount,
                "total_cents": round(quantity * unit_amount),
            }
        )
    return cleaned


def _refresh_invoice(invoice: PartnerInvoice) -> None:
    confirmed = invoice.payments.filter(
        status=PartnerPayment.Status.CONFIRMED
    ).aggregate(value=Sum("amount_cents"))["value"] or 0
    processor_fees = invoice.payments.filter(
        status=PartnerPayment.Status.CONFIRMED
    ).aggregate(value=Sum("processor_fee_amount_cents"))["value"] or 0

    invoice.amount_paid_cents = min(int(confirmed), int(invoice.total_cents))
    invoice.processor_fee_amount_cents = int(processor_fees)
    if invoice.amount_paid_cents <= 0:
        if invoice.status in {
            PartnerInvoice.Status.PARTIALLY_PAID,
            PartnerInvoice.Status.PAID,
        }:
            invoice.status = PartnerInvoice.Status.APPROVED
        invoice.paid_at = None
    elif invoice.amount_paid_cents < invoice.total_cents:
        invoice.status = PartnerInvoice.Status.PARTIALLY_PAID
        invoice.paid_at = None
    else:
        invoice.status = PartnerInvoice.Status.PAID
        invoice.paid_at = invoice.paid_at or timezone.now()

    invoice.save(
        update_fields=[
            "amount_paid_cents",
            "processor_fee_amount_cents",
            "status",
            "paid_at",
            "platform_fee_amount_cents",
            "updated_at",
        ]
    )


class PartnerInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = PartnerInvoiceSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _business(self):
        business, _, _ = _business_context(self.request)
        return business

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["active_business_id"] = self._business().id
        return context

    def get_queryset(self):
        business = self._business()
        return (
            PartnerInvoice.objects.filter(
                Q(issuing_business=business)
                | Q(paying_business=business)
            )
            .select_related(
                "work_ticket",
                "work_ticket__source_ticket",
                "issuing_business",
                "paying_business",
                "created_by",
                "approved_by",
            )
            .prefetch_related("payments__allocations")
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        business = self._business()
        try:
            work_ticket_id = int(request.data.get("work_ticket"))
        except (TypeError, ValueError):
            raise ValidationError(
                {"work_ticket": "Use a numeric partner work ticket ID."}
            )
        work = PartnerWorkTicket.objects.filter(
            id=work_ticket_id,
            partner_business=business,
        ).select_related(
            "hiring_business",
            "source_ticket",
        ).first()
        if not work:
            raise ValidationError(
                {"work_ticket": "Partner work ticket was not found."}
            )
        if work.status not in {
            PartnerWorkTicket.Status.ACCEPTED,
            PartnerWorkTicket.Status.SCHEDULED,
            PartnerWorkTicket.Status.EN_ROUTE,
            PartnerWorkTicket.Status.ON_SITE,
            PartnerWorkTicket.Status.IN_PROGRESS,
            PartnerWorkTicket.Status.BLOCKED,
            PartnerWorkTicket.Status.AWAITING_REVIEW,
            PartnerWorkTicket.Status.COMPLETED,
        }:
            raise ValidationError(
                {"work_ticket": "Work status does not allow invoicing."}
            )

        items = _line_items(request.data.get("line_items"))
        subtotal = _whole_cents(
            request.data.get(
                "subtotal_cents",
                sum(item["total_cents"] for item in items)
                or work.agreed_amount_cents,
            ),
            "subtotal_cents",
        )
        tax = _whole_cents(request.data.get("tax_cents", 0), "tax_cents")
        total = _whole_cents(
            request.data.get("total_cents", subtotal + tax),
            "total_cents",
            allow_zero=False,
        )
        if total != subtotal + tax:
            raise ValidationError(
                {"total_cents": "Total must equal subtotal plus tax."}
            )

        fee_treatment = str(
            request.data.get("fee_treatment")
            or PartnerInvoice.FeeTreatment.LINKED_SETTLEMENT
        ).strip().upper()
        valid_fee_treatments = {
            value for value, _ in PartnerInvoice.FeeTreatment.choices
        }
        if fee_treatment not in valid_fee_treatments:
            raise ValidationError(
                {"fee_treatment": "Unknown fee treatment."}
            )
        if (
            fee_treatment == PartnerInvoice.FeeTreatment.INDEPENDENT_B2B
            and work.source_ticket_id
        ):
            raise ValidationError(
                {
                    "fee_treatment": (
                        "Work linked to a customer ticket must use "
                        "LINKED_SETTLEMENT to avoid duplicate platform fees."
                    )
                }
            )

        invoice = PartnerInvoice.objects.create(
            work_ticket=work,
            issuing_business=business,
            paying_business=work.hiring_business,
            invoice_number=str(
                request.data.get("invoice_number") or ""
            ).strip(),
            title=str(request.data.get("title") or work.title or "").strip(),
            notes=str(request.data.get("notes") or "").strip(),
            line_items=items,
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=total,
            fee_treatment=fee_treatment,
            due_date=request.data.get("due_date") or None,
            created_by=request.user,
        )
        return Response(
            self.get_serializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        invoice = self.get_object()
        business = self._business()
        if (
            business.id != invoice.issuing_business_id
            or invoice.status != PartnerInvoice.Status.DRAFT
        ):
            raise ValidationError(
                {"invoice": "Only the issuer can edit a draft invoice."}
            )

        for field in ("invoice_number", "title", "notes", "due_date"):
            if field in request.data:
                setattr(invoice, field, request.data.get(field) or "")
        if "line_items" in request.data:
            invoice.line_items = _line_items(
                request.data.get("line_items")
            )
        if "subtotal_cents" in request.data:
            invoice.subtotal_cents = _whole_cents(
                request.data.get("subtotal_cents"),
                "subtotal_cents",
            )
        elif "line_items" in request.data:
            invoice.subtotal_cents = sum(
                item["total_cents"] for item in invoice.line_items
            )
        if "tax_cents" in request.data:
            invoice.tax_cents = _whole_cents(
                request.data.get("tax_cents"),
                "tax_cents",
            )
        invoice.total_cents = invoice.subtotal_cents + invoice.tax_cents
        if invoice.total_cents <= 0:
            raise ValidationError(
                {"total_cents": "Invoice total must be greater than zero."}
            )
        invoice.save()
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        invoice = self.get_object()
        business = self._business()
        if business.id != invoice.issuing_business_id:
            raise ValidationError(
                {"business": "Only the issuing business can submit."}
            )
        if invoice.status != PartnerInvoice.Status.DRAFT:
            raise ValidationError(
                {"status": "Only draft invoices can submit."}
            )
        invoice.status = PartnerInvoice.Status.SUBMITTED
        invoice.submitted_at = timezone.now()
        invoice.save(
            update_fields=[
                "status",
                "submitted_at",
                "platform_fee_amount_cents",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        invoice = self.get_object()
        business = self._business()
        if business.id != invoice.paying_business_id:
            raise ValidationError(
                {"business": "Only the paying business can review."}
            )
        if invoice.status != PartnerInvoice.Status.SUBMITTED:
            raise ValidationError(
                {"status": "Invoice is not awaiting review."}
            )
        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()
        if decision not in {"APPROVE", "DISPUTE"}:
            raise ValidationError(
                {"decision": "Use APPROVE or DISPUTE."}
            )

        if decision == "APPROVE":
            invoice.status = PartnerInvoice.Status.APPROVED
            invoice.approved_by = request.user
            invoice.approved_at = timezone.now()
        else:
            invoice.status = PartnerInvoice.Status.DISPUTED
            invoice.disputed_at = timezone.now()
            invoice.notes = str(
                request.data.get("dispute_notes")
                or invoice.notes
                or ""
            ).strip()
        invoice.save()
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, pk=None):
        invoice = self.get_object()
        business = self._business()
        if business.id != invoice.issuing_business_id:
            raise ValidationError(
                {"business": "Only the issuing business can void."}
            )
        if invoice.amount_paid_cents:
            raise ValidationError(
                {"invoice": "Paid invoices cannot be voided."}
            )
        invoice.status = PartnerInvoice.Status.VOID
        invoice.voided_at = timezone.now()
        invoice.save()
        return Response(self.get_serializer(invoice).data)


class PartnerPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PartnerPaymentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def _business(self):
        business, _, _ = _business_context(self.request)
        return business

    def get_queryset(self):
        business = self._business()
        return (
            PartnerPayment.objects.filter(
                Q(invoice__issuing_business=business)
                | Q(invoice__paying_business=business)
            )
            .select_related(
                "invoice",
                "invoice__work_ticket",
                "recorded_by",
                "confirmed_by",
            )
            .prefetch_related("allocations")
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        business = self._business()
        try:
            invoice_id = int(request.data.get("invoice"))
        except (TypeError, ValueError):
            raise ValidationError({"invoice": "Use a numeric invoice ID."})

        invoice = PartnerInvoice.objects.filter(
            id=invoice_id,
            paying_business=business,
            status__in=[
                PartnerInvoice.Status.APPROVED,
                PartnerInvoice.Status.PARTIALLY_PAID,
            ],
        ).select_related(
            "work_ticket",
            "work_ticket__source_ticket",
        ).first()
        if not invoice:
            raise ValidationError(
                {"invoice": "Approved payable invoice was not found."}
            )

        amount = _whole_cents(
            request.data.get("amount_cents"),
            "amount_cents",
            allow_zero=False,
        )
        if amount > invoice.balance_due_cents:
            raise ValidationError(
                {"amount_cents": "Payment exceeds the balance due."}
            )

        method = str(
            request.data.get("method") or PartnerPayment.Method.ACH
        ).strip().upper()
        valid_methods = {
            value for value, _ in PartnerPayment.Method.choices
        }
        if method not in valid_methods:
            raise ValidationError({"method": "Unknown payment method."})

        processor_fee = _whole_cents(
            request.data.get("processor_fee_amount_cents", 0),
            "processor_fee_amount_cents",
        )
        external_reference = str(
            request.data.get("external_reference") or ""
        ).strip()
        receipt_url = str(
            request.data.get("receipt_url") or ""
        ).strip()

        auto_confirm = (
            method in AUTO_CONFIRM_METHODS
            and bool(
                request.data.get("stripe_payment_intent_id")
                or request.data.get("stripe_charge_id")
                or request.data.get("provider_confirmed")
            )
        )
        if method not in AUTO_CONFIRM_METHODS and not external_reference:
            raise ValidationError(
                {
                    "external_reference": (
                        "External payments require a check number, "
                        "confirmation code, or other reference."
                    )
                }
            )

        payment = PartnerPayment.objects.create(
            invoice=invoice,
            amount_cents=amount,
            method=method,
            status=(
                PartnerPayment.Status.CONFIRMED
                if auto_confirm
                else PartnerPayment.Status.PENDING
            ),
            processor_fee_amount_cents=processor_fee,
            external_reference=external_reference,
            receipt_url=receipt_url,
            notes=str(request.data.get("notes") or "").strip(),
            stripe_payment_intent_id=str(
                request.data.get("stripe_payment_intent_id") or ""
            ).strip(),
            stripe_charge_id=str(
                request.data.get("stripe_charge_id") or ""
            ).strip(),
            stripe_transfer_id=str(
                request.data.get("stripe_transfer_id") or ""
            ).strip(),
            recorded_by=request.user,
            confirmed_by=request.user if auto_confirm else None,
            confirmed_at=timezone.now() if auto_confirm else None,
        )

        if auto_confirm:
            self._apply_confirmed_payment(payment)

        return Response(
            self.get_serializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

    def _apply_confirmed_payment(self, payment: PartnerPayment) -> None:
        with transaction.atomic():
            invoice = PartnerInvoice.objects.select_for_update().get(
                id=payment.invoice_id
            )
            source = invoice.work_ticket.source_ticket

            PartnerPaymentAllocation.objects.get_or_create(
                partner_payment=payment,
                source_ticket=source,
                defaults={
                    "allocated_amount_cents": payment.amount_cents,
                    "lineage_key": invoice.fee_lineage_key,
                    "platform_fee_already_assessed": (
                        invoice.fee_treatment
                        == PartnerInvoice.FeeTreatment.LINKED_SETTLEMENT
                    ),
                    "notes": (
                        "Linked partner settlement allocation."
                    ),
                },
            )

            _refresh_invoice(invoice)
            invoice.refresh_from_db(
                fields=["amount_paid_cents", "total_cents"]
            )
            source.actual_cost_cents = min(
                int(invoice.amount_paid_cents or 0),
                int(invoice.total_cents),
            )
            source.save(update_fields=["actual_cost_cents"])

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        payment = self.get_object()
        business = self._business()
        if business.id != payment.invoice.paying_business_id:
            raise ValidationError(
                {"business": "Only the paying business can confirm payment."}
            )
        if payment.status != PartnerPayment.Status.PENDING:
            raise ValidationError(
                {"status": "Only pending payments can be confirmed."}
            )

        payment.status = PartnerPayment.Status.CONFIRMED
        payment.confirmed_by = request.user
        payment.confirmed_at = timezone.now()
        payment.external_reference = str(
            request.data.get("external_reference")
            or payment.external_reference
            or ""
        ).strip()
        payment.receipt_url = str(
            request.data.get("receipt_url")
            or payment.receipt_url
            or ""
        ).strip()
        if (
            payment.method not in AUTO_CONFIRM_METHODS
            and not payment.external_reference
        ):
            raise ValidationError(
                {
                    "external_reference": (
                        "External payments require a confirmation reference."
                    )
                }
            )
        payment.save()
        self._apply_confirmed_payment(payment)
        return Response(self.get_serializer(payment).data)
