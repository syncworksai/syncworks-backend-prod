from __future__ import annotations

import csv
from datetime import datetime, time

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from user_accounts.models import BusinessCustomer, Ticket
from user_accounts.viewsets.ticket_conversations import _business_context


def _filename_part(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in str(value or "").strip())
    return "-".join(part for part in cleaned.split("-") if part) or "business"


def _csv_response(filename: str):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    return response


def _date_boundary(value: str, field_name: str, end_of_day: bool = False):
    raw = str(value or "").strip()
    if not raw:
        return None
    day = parse_date(raw)
    if not day:
        raise ValidationError({field_name: "Use YYYY-MM-DD."})
    return timezone.make_aware(datetime.combine(day, time.max if end_of_day else time.min))


def _iso(value):
    return timezone.localtime(value).isoformat() if value else ""


def _join_tags(value):
    return ", ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")


class BusinessExportViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _ticket_queryset(self, request):
        business, _, _ = _business_context(request)
        queryset = Ticket.objects.filter(assigned_business=business).select_related(
            "business_customer", "category", "assigned_member"
        ).order_by("-created_at", "-id")

        scope = str(request.query_params.get("scope") or "all").strip().lower()
        if scope == "syncworks":
            queryset = queryset.filter(is_imported=False, exclude_from_operational_kpis=False)
        elif scope == "imported":
            queryset = queryset.filter(is_imported=True)
        elif scope != "all":
            raise ValidationError({"scope": "Use all, syncworks, or imported."})

        status_value = str(request.query_params.get("status") or "").strip().upper()
        if status_value:
            if status_value not in {value for value, _ in Ticket.Status.choices}:
                raise ValidationError({"status": "Unknown ticket status."})
            queryset = queryset.filter(status=status_value)

        payment_method = str(request.query_params.get("payment_method") or "").strip().upper()
        if payment_method:
            if payment_method not in {value for value, _ in Ticket.PaymentMethod.choices}:
                raise ValidationError({"payment_method": "Unknown payment method."})
            queryset = queryset.filter(payment_method=payment_method)

        customer_id = str(request.query_params.get("customer_id") or "").strip()
        if customer_id:
            try:
                queryset = queryset.filter(business_customer_id=int(customer_id))
            except ValueError:
                raise ValidationError({"customer_id": "Use a numeric customer ID."})

        date_from = _date_boundary(request.query_params.get("date_from"), "date_from")
        date_to = _date_boundary(request.query_params.get("date_to"), "date_to", end_of_day=True)
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_range": "date_from must be before date_to."})
        return business, queryset, scope

    @action(detail=False, methods=["get"], url_path="customers.csv")
    def customers_csv(self, request):
        business, _, _ = _business_context(request)
        queryset = BusinessCustomer.objects.filter(business=business).order_by("name", "company_name", "id")
        source = str(request.query_params.get("source") or "all").strip().lower()
        if source == "syncworks": queryset = queryset.filter(is_imported=False)
        elif source == "imported": queryset = queryset.filter(is_imported=True)
        elif source != "all": raise ValidationError({"source": "Use all, syncworks, or imported."})

        response = _csv_response(f"{_filename_part(business.name)}-customers-{timezone.localdate().isoformat()}.csv")
        writer = csv.writer(response)
        writer.writerow(["customer_id","name","company_name","email","phone","billing_address","service_address","unit","city","state","service_zip","contact_preference","payment_preference","access_notes","notes","tags","record_source","source_system","external_customer_id","is_imported","exclude_from_kpis","first_service_at","last_service_at","ticket_count","completed_ticket_count","cancelled_ticket_count","lifetime_revenue","last_service_label","created_at","updated_at"])
        for c in queryset.iterator(chunk_size=500):
            writer.writerow([c.id,c.name,c.company_name,c.email,c.phone,c.billing_address,c.service_address,c.unit,c.city,c.state,c.service_zip,c.contact_preference,c.payment_preference,c.access_notes,c.notes,_join_tags(c.tags),c.record_source,c.source_system,c.external_customer_id,c.is_imported,c.exclude_from_kpis,_iso(c.first_service_at),_iso(c.last_service_at),c.ticket_count,c.completed_ticket_count,c.cancelled_ticket_count,f"{c.lifetime_revenue_cents / 100:.2f}",c.last_service_label,_iso(c.created_at),_iso(c.updated_at)])
        return response

    @action(detail=False, methods=["get"], url_path="tickets.csv")
    def tickets_csv(self, request):
        business, queryset, scope = self._ticket_queryset(request)
        response = _csv_response(f"{_filename_part(business.name)}-tickets-{scope}-{timezone.localdate().isoformat()}.csv")
        writer = csv.writer(response)
        writer.writerow(["ticket_id","ticket_code","customer_id","customer_name","customer_company","customer_email","customer_phone","service_address","service_zip","category","status","payment_method","total_amount","is_marketplace","is_imported","source_system","external_ticket_id","import_batch_id","exclude_from_operational_kpis","assigned_member","created_at","original_created_at","scheduled_at","started_at","completed_at","invoiced_at","paid_at","cancelled_at","closed_at","archived_at"])
        for t in queryset.iterator(chunk_size=500):
            c=t.business_customer; m=t.assigned_member
            member=(m.get_full_name() or m.email) if m else ""
            writer.writerow([t.id,t.ticket_code,c.id if c else "",c.name if c else "",c.company_name if c else "",c.email if c else "",c.phone if c else "",t.service_address,t.service_zip,t.category.name if t.category else "",t.status,t.payment_method,f"{t.total_amount_cents / 100:.2f}",t.is_marketplace,t.is_imported,t.source_system,t.external_ticket_id,t.import_batch_id,t.exclude_from_operational_kpis,member,_iso(t.created_at),_iso(t.original_created_at),_iso(t.scheduled_at),_iso(t.started_at),_iso(t.completed_at),_iso(t.invoiced_at),_iso(t.paid_at),_iso(t.cancelled_at),_iso(t.closed_at),_iso(t.archived_at)])
        return response
