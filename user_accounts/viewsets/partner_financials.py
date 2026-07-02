from __future__ import annotations

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    PartnerWorkChangeOrder,
    PartnerWorkEstimate,
    PartnerWorkTicket,
)
from user_accounts.serializers.partner_financials import (
    PartnerWorkChangeOrderSerializer,
    PartnerWorkEstimateSerializer,
)
from user_accounts.viewsets.ticket_conversations import _business_context


def _whole_cents(value, field_name: str, allow_negative: bool = False) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        raise ValidationError({field_name: "Use a whole number of cents."})
    if not allow_negative and parsed < 0:
        raise ValidationError({field_name: "Amount cannot be negative."})
    return parsed


def _validate_line_items(value):
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
        unit_amount_cents = _whole_cents(
            item.get("unit_amount_cents", 0),
            f"line_items[{index}].unit_amount_cents",
        )
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
        cleaned.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_amount_cents": unit_amount_cents,
                "total_cents": round(quantity * unit_amount_cents),
            }
        )
    return cleaned


class _PartnerFinancialBase:
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _business(self):
        business, _, _ = _business_context(self.request)
        return business

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["active_business_id"] = self._business().id
        return context

    def _work_ticket(self, work_ticket_id):
        business = self._business()
        return PartnerWorkTicket.objects.filter(
            id=work_ticket_id,
        ).filter(
            Q(hiring_business=business) | Q(partner_business=business)
        ).select_related(
            "source_ticket",
            "hiring_business",
            "partner_business",
        ).first()


class PartnerWorkEstimateViewSet(
    _PartnerFinancialBase,
    viewsets.ModelViewSet,
):
    serializer_class = PartnerWorkEstimateSerializer

    def get_queryset(self):
        business = self._business()
        return PartnerWorkEstimate.objects.filter(
            Q(work_ticket__hiring_business=business)
            | Q(work_ticket__partner_business=business)
        ).select_related(
            "work_ticket",
            "work_ticket__source_ticket",
            "work_ticket__hiring_business",
            "work_ticket__partner_business",
            "created_by",
            "reviewed_by",
        ).distinct()

    def create(self, request, *args, **kwargs):
        business = self._business()
        try:
            work_ticket_id = int(request.data.get("work_ticket"))
        except (TypeError, ValueError):
            raise ValidationError(
                {"work_ticket": "Use a numeric partner work ticket ID."}
            )
        work = self._work_ticket(work_ticket_id)
        if not work:
            raise ValidationError({"work_ticket": "Work ticket was not found."})
        if business.id != work.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can draft an estimate."}
            )
        if work.status in {
            PartnerWorkTicket.Status.DECLINED,
            PartnerWorkTicket.Status.CANCELLED,
            PartnerWorkTicket.Status.COMPLETED,
        }:
            raise ValidationError(
                {"work_ticket": "This work ticket cannot receive estimates."}
            )

        latest = PartnerWorkEstimate.objects.filter(
            work_ticket=work
        ).aggregate(value=Max("revision"))["value"] or 0
        line_items = _validate_line_items(request.data.get("line_items"))
        subtotal = _whole_cents(
            request.data.get(
                "subtotal_cents",
                sum(item["total_cents"] for item in line_items),
            ),
            "subtotal_cents",
        )
        tax = _whole_cents(
            request.data.get("tax_cents", 0),
            "tax_cents",
        )
        total = _whole_cents(
            request.data.get("total_cents", subtotal + tax),
            "total_cents",
        )
        if total != subtotal + tax:
            raise ValidationError(
                {"total_cents": "Total must equal subtotal plus tax."}
            )

        estimate = PartnerWorkEstimate.objects.create(
            work_ticket=work,
            revision=latest + 1,
            title=str(request.data.get("title") or "").strip(),
            scope=str(request.data.get("scope") or work.scope or "").strip(),
            line_items=line_items,
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=total,
            estimated_days=(
                int(request.data.get("estimated_days"))
                if request.data.get("estimated_days") not in (None, "")
                else None
            ),
            valid_until=request.data.get("valid_until") or None,
            partner_notes=str(
                request.data.get("partner_notes") or ""
            ).strip(),
            created_by=request.user,
        )
        return Response(
            self.get_serializer(estimate).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        estimate = self.get_object()
        business = self._business()
        if (
            business.id != estimate.work_ticket.partner_business_id
            or estimate.status != PartnerWorkEstimate.Status.DRAFT
        ):
            raise ValidationError(
                {"estimate": "Only the partner can edit a draft estimate."}
            )

        for field in (
            "title",
            "scope",
            "partner_notes",
            "valid_until",
        ):
            if field in request.data:
                setattr(estimate, field, request.data.get(field) or "")
        if "estimated_days" in request.data:
            estimate.estimated_days = (
                int(request.data.get("estimated_days"))
                if request.data.get("estimated_days") not in (None, "")
                else None
            )
        if "line_items" in request.data:
            estimate.line_items = _validate_line_items(
                request.data.get("line_items")
            )
        if "subtotal_cents" in request.data:
            estimate.subtotal_cents = _whole_cents(
                request.data.get("subtotal_cents"),
                "subtotal_cents",
            )
        elif "line_items" in request.data:
            estimate.subtotal_cents = sum(
                item["total_cents"] for item in estimate.line_items
            )
        if "tax_cents" in request.data:
            estimate.tax_cents = _whole_cents(
                request.data.get("tax_cents"),
                "tax_cents",
            )
        estimate.total_cents = (
            estimate.subtotal_cents + estimate.tax_cents
        )
        estimate.save()
        return Response(self.get_serializer(estimate).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        estimate = self.get_object()
        business = self._business()
        if business.id != estimate.work_ticket.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can submit."}
            )
        if estimate.status != PartnerWorkEstimate.Status.DRAFT:
            raise ValidationError({"status": "Only draft estimates can submit."})
        if estimate.total_cents <= 0:
            raise ValidationError(
                {"total_cents": "Estimate total must be greater than zero."}
            )
        estimate.status = PartnerWorkEstimate.Status.SUBMITTED
        estimate.submitted_at = timezone.now()
        estimate.save(
            update_fields=["status", "submitted_at", "updated_at"]
        )
        return Response(self.get_serializer(estimate).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        estimate = self.get_object()
        business = self._business()
        if business.id != estimate.work_ticket.hiring_business_id:
            raise ValidationError(
                {"business": "Only the hiring business can review."}
            )
        if estimate.status != PartnerWorkEstimate.Status.SUBMITTED:
            raise ValidationError(
                {"status": "Estimate is not awaiting review."}
            )
        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ValidationError({"decision": "Use APPROVE or REJECT."})

        now = timezone.now()
        with transaction.atomic():
            estimate.reviewed_by = request.user
            estimate.reviewed_at = now
            estimate.hiring_business_notes = str(
                request.data.get("hiring_business_notes") or ""
            ).strip()
            if decision == "APPROVE":
                estimate.status = PartnerWorkEstimate.Status.APPROVED
                PartnerWorkEstimate.objects.filter(
                    work_ticket=estimate.work_ticket,
                    status=PartnerWorkEstimate.Status.APPROVED,
                ).exclude(id=estimate.id).update(
                    status=PartnerWorkEstimate.Status.SUPERSEDED
                )
                work = estimate.work_ticket
                work.agreed_amount_cents = estimate.total_cents
                work.save(
                    update_fields=["agreed_amount_cents", "updated_at"]
                )
                source = work.source_ticket
                source.projected_cost_cents = estimate.total_cents
                source.save(update_fields=["projected_cost_cents"])
            else:
                estimate.status = PartnerWorkEstimate.Status.REJECTED
            estimate.save()

        return Response(self.get_serializer(estimate).data)


class PartnerWorkChangeOrderViewSet(
    _PartnerFinancialBase,
    viewsets.ModelViewSet,
):
    serializer_class = PartnerWorkChangeOrderSerializer

    def get_queryset(self):
        business = self._business()
        return PartnerWorkChangeOrder.objects.filter(
            Q(work_ticket__hiring_business=business)
            | Q(work_ticket__partner_business=business)
        ).select_related(
            "work_ticket",
            "work_ticket__source_ticket",
            "work_ticket__hiring_business",
            "work_ticket__partner_business",
            "created_by",
            "reviewed_by",
        ).distinct()

    def create(self, request, *args, **kwargs):
        business = self._business()
        try:
            work_ticket_id = int(request.data.get("work_ticket"))
        except (TypeError, ValueError):
            raise ValidationError(
                {"work_ticket": "Use a numeric partner work ticket ID."}
            )
        work = self._work_ticket(work_ticket_id)
        if not work:
            raise ValidationError({"work_ticket": "Work ticket was not found."})
        if business.id != work.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner can propose a change order."}
            )
        if work.status in {
            PartnerWorkTicket.Status.OFFERED,
            PartnerWorkTicket.Status.DECLINED,
            PartnerWorkTicket.Status.CANCELLED,
            PartnerWorkTicket.Status.COMPLETED,
        }:
            raise ValidationError(
                {"work_ticket": "Work status does not allow change orders."}
            )

        latest = PartnerWorkChangeOrder.objects.filter(
            work_ticket=work
        ).aggregate(value=Max("sequence"))["value"] or 0
        change = PartnerWorkChangeOrder.objects.create(
            work_ticket=work,
            sequence=latest + 1,
            title=str(request.data.get("title") or "").strip(),
            reason=str(request.data.get("reason") or "").strip(),
            scope_delta=str(request.data.get("scope_delta") or "").strip(),
            line_items=_validate_line_items(request.data.get("line_items")),
            partner_amount_delta_cents=_whole_cents(
                request.data.get("partner_amount_delta_cents"),
                "partner_amount_delta_cents",
                allow_negative=True,
            ),
            schedule_days_delta=int(
                request.data.get("schedule_days_delta") or 0
            ),
            partner_notes=str(
                request.data.get("partner_notes") or ""
            ).strip(),
            created_by=request.user,
        )
        if not change.title:
            change.delete()
            raise ValidationError({"title": "A title is required."})
        return Response(
            self.get_serializer(change).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        change = self.get_object()
        business = self._business()
        if (
            business.id != change.work_ticket.partner_business_id
            or change.status != PartnerWorkChangeOrder.Status.DRAFT
        ):
            raise ValidationError(
                {"change_order": "Only the partner can edit a draft."}
            )
        for field in (
            "title",
            "reason",
            "scope_delta",
            "partner_notes",
        ):
            if field in request.data:
                setattr(change, field, request.data.get(field) or "")
        if "line_items" in request.data:
            change.line_items = _validate_line_items(
                request.data.get("line_items")
            )
        if "partner_amount_delta_cents" in request.data:
            change.partner_amount_delta_cents = _whole_cents(
                request.data.get("partner_amount_delta_cents"),
                "partner_amount_delta_cents",
                allow_negative=True,
            )
        if "schedule_days_delta" in request.data:
            change.schedule_days_delta = int(
                request.data.get("schedule_days_delta") or 0
            )
        change.save()
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        change = self.get_object()
        business = self._business()
        if business.id != change.work_ticket.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can submit."}
            )
        if change.status != PartnerWorkChangeOrder.Status.DRAFT:
            raise ValidationError(
                {"status": "Only draft change orders can submit."}
            )
        change.status = PartnerWorkChangeOrder.Status.SUBMITTED
        change.submitted_at = timezone.now()
        change.save(
            update_fields=["status", "submitted_at", "updated_at"]
        )
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        change = self.get_object()
        business = self._business()
        if business.id != change.work_ticket.hiring_business_id:
            raise ValidationError(
                {"business": "Only the hiring business can review."}
            )
        if change.status != PartnerWorkChangeOrder.Status.SUBMITTED:
            raise ValidationError(
                {"status": "Change order is not awaiting review."}
            )
        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ValidationError({"decision": "Use APPROVE or REJECT."})

        customer_delta = _whole_cents(
            request.data.get("customer_amount_delta_cents"),
            "customer_amount_delta_cents",
            allow_negative=True,
        )
        now = timezone.now()
        with transaction.atomic():
            change.reviewed_by = request.user
            change.reviewed_at = now
            change.hiring_business_notes = str(
                request.data.get("hiring_business_notes") or ""
            ).strip()
            if decision == "APPROVE":
                change.status = PartnerWorkChangeOrder.Status.APPROVED
                change.customer_amount_delta_cents = customer_delta
                work = change.work_ticket
                work.agreed_amount_cents = max(
                    work.agreed_amount_cents
                    + change.partner_amount_delta_cents,
                    0,
                )
                work.save(
                    update_fields=["agreed_amount_cents", "updated_at"]
                )
                source = work.source_ticket
                source.projected_cost_cents = max(
                    source.projected_cost_cents
                    + change.partner_amount_delta_cents,
                    0,
                )
                source.projected_customer_amount_cents = max(
                    source.projected_customer_amount_cents
                    + customer_delta,
                    0,
                )
                source.save(
                    update_fields=[
                        "projected_cost_cents",
                        "projected_customer_amount_cents",
                    ]
                )
            else:
                change.status = PartnerWorkChangeOrder.Status.REJECTED
            change.save()

        return Response(self.get_serializer(change).data)
