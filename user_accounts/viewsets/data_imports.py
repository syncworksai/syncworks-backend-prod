from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    BusinessCustomer,
    BusinessDataImport,
    ServiceCategory,
    Ticket,
)
from user_accounts.models.business_customers import normalize_phone
from user_accounts.serializers.data_imports import BusinessDataImportSerializer
from user_accounts.viewsets.ticket_conversations import _business_context


MAX_IMPORT_ROWS = 5000
MAX_IMPORT_FILE_BYTES = 5 * 1024 * 1024
MAX_REPORTED_ERRORS = 100
MAX_SAMPLE_ROWS = 10

ALIASES = {
    "external_customer_id": {
        "external_customer_id", "customer_id", "client_id", "account_id"
    },
    "external_ticket_id": {
        "external_ticket_id", "ticket_id", "job_id", "work_order_id", "order_id"
    },
    "name": {"name", "customer_name", "client_name", "contact_name"},
    "company_name": {"company_name", "business_name", "organization"},
    "email": {"email", "customer_email", "client_email"},
    "phone": {"phone", "phone_number", "customer_phone", "client_phone"},
    "service_address": {
        "service_address", "address", "job_address", "street"
    },
    "billing_address": {"billing_address"},
    "unit": {"unit", "apt", "suite"},
    "city": {"city"},
    "state": {"state", "province"},
    "service_zip": {"service_zip", "zip", "zip_code", "postal_code"},
    "access_notes": {"access_notes", "access", "entry_notes"},
    "notes": {"notes", "customer_notes", "job_notes", "description"},
    "tags": {"tags"},
    "contact_preference": {"contact_preference", "preferred_contact"},
    "payment_preference": {"payment_preference", "preferred_payment"},
    "status": {"status", "ticket_status", "job_status"},
    "category": {"category", "service", "service_name", "job_type"},
    "created_at": {"created_at", "created_date", "opened_at", "job_created"},
    "scheduled_at": {"scheduled_at", "scheduled_date", "appointment_date"},
    "completed_at": {"completed_at", "completed_date", "closed_date"},
    "cancelled_at": {"cancelled_at", "cancelled_date"},
    "paid_at": {"paid_at", "paid_date", "payment_date"},
    "total_amount": {
        "total_amount", "amount", "invoice_amount", "job_total", "total"
    },
    "payment_method": {"payment_method", "paid_via"},
}


def _clean_header(value):
    raw = str(value or "").strip().lower().replace("-", "_")
    return "_".join(raw.split())


def _decode_csv(file_obj):
    if not file_obj:
        raise ValidationError({"file": "CSV file is required."})

    size = int(getattr(file_obj, "size", 0) or 0)
    if size > MAX_IMPORT_FILE_BYTES:
        raise ValidationError({"file": "CSV file must be 5MB or smaller."})

    name = str(getattr(file_obj, "name", "") or "")
    if not name.lower().endswith(".csv"):
        raise ValidationError(
            {"file": "Historical imports currently support CSV files only."}
        )

    raw = file_obj.read()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ValidationError(
        {"file": "Unable to decode CSV. Save the file as UTF-8 CSV."}
    )


def _read_rows(file_obj):
    text = _decode_csv(file_obj)
    reader = csv.DictReader(io.StringIO(text))
    headers = [_clean_header(value) for value in (reader.fieldnames or [])]

    if not headers:
        raise ValidationError({"file": "CSV has no header row."})
    if len(headers) != len(set(headers)):
        raise ValidationError(
            {"file": "CSV contains duplicate normalized column names."}
        )

    rows = []
    for row_number, source in enumerate(reader, start=2):
        if len(rows) >= MAX_IMPORT_ROWS:
            raise ValidationError(
                {"file": f"CSV exceeds the {MAX_IMPORT_ROWS}-row limit."}
            )

        normalized = {
            _clean_header(key): str(value or "").strip()
            for key, value in source.items()
        }
        if any(normalized.values()):
            rows.append((row_number, normalized))

    if not rows:
        raise ValidationError({"file": "CSV contains no data rows."})

    return headers, rows


def _parse_mapping(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except Exception:
        raise ValidationError({"column_mapping": "Must be valid JSON."})
    if not isinstance(parsed, dict):
        raise ValidationError({"column_mapping": "Must be a JSON object."})
    return parsed


def _build_mapping(headers, supplied):
    header_set = set(headers)
    mapping = {}

    for canonical, aliases in ALIASES.items():
        requested = _clean_header(supplied.get(canonical, ""))
        if requested:
            if requested not in header_set:
                raise ValidationError(
                    {
                        "column_mapping": (
                            f"Column '{requested}' was not found for '{canonical}'."
                        )
                    }
                )
            mapping[canonical] = requested
            continue

        mapping[canonical] = next(
            (candidate for candidate in aliases if candidate in header_set),
            "",
        )

    return mapping


def _value(row, mapping, key):
    column = mapping.get(key) or ""
    return str(row.get(column, "") or "").strip() if column else ""


def _parse_datetime_value(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = parse_datetime(raw)
    if parsed:
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

    day = parse_date(raw)
    if day:
        return timezone.make_aware(datetime.combine(day, datetime.min.time()))

    for fmt in (
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%m-%d-%Y",
    ):
        try:
            return timezone.make_aware(datetime.strptime(raw, fmt))
        except ValueError:
            continue

    return None


def _money_cents(value):
    raw = str(value or "").replace("$", "").replace(",", "").strip()
    if not raw:
        return 0
    try:
        amount = Decimal(raw)
        if amount < 0:
            return None
        return int(
            (amount * Decimal("100")).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
    except (InvalidOperation, ValueError):
        return None


def _validate_row(row_number, row, mapping, import_type):
    values = {
        key: _value(row, mapping, key)
        for key in mapping
        if mapping.get(key)
    }
    errors = []

    has_customer_identity = any(
        values.get(key)
        for key in (
            "name",
            "company_name",
            "email",
            "phone",
            "external_customer_id",
        )
    )
    if not has_customer_identity:
        errors.append(
            "Provide name, company name, email, phone, or external customer ID."
        )

    if import_type == BusinessDataImport.ImportType.TICKETS:
        if not values.get("external_ticket_id"):
            errors.append("External ticket ID is required for ticket imports.")

        if _money_cents(values.get("total_amount")) is None:
            errors.append("Total amount is not a valid non-negative number.")

        for field in (
            "created_at",
            "scheduled_at",
            "completed_at",
            "cancelled_at",
            "paid_at",
        ):
            raw = values.get(field)
            if raw and not _parse_datetime_value(raw):
                errors.append(f"{field} is not a recognized date.")

    return {
        "row": row_number,
        "valid": not errors,
        "errors": errors,
        "values": values,
    }


def _customer_payload(values, source_system, batch_id):
    tags = [
        item.strip()
        for item in str(values.get("tags") or "").replace(";", ",").split(",")
        if item.strip()
    ]
    return {
        "name": str(values.get("name") or "").strip(),
        "company_name": str(values.get("company_name") or "").strip(),
        "email": str(values.get("email") or "").strip().lower(),
        "phone": str(values.get("phone") or "").strip(),
        "billing_address": str(values.get("billing_address") or "").strip(),
        "service_address": str(values.get("service_address") or "").strip(),
        "unit": str(values.get("unit") or "").strip(),
        "city": str(values.get("city") or "").strip(),
        "state": str(values.get("state") or "").strip(),
        "service_zip": str(values.get("service_zip") or "").strip(),
        "access_notes": str(values.get("access_notes") or "").strip(),
        "contact_preference": (
            str(values.get("contact_preference") or "").strip() or "either"
        ),
        "payment_preference": (
            str(values.get("payment_preference") or "").strip()
            or "quote_first"
        ),
        "notes": str(values.get("notes") or "").strip(),
        "tags": tags,
        "record_source": BusinessCustomer.RecordSource.IMPORTED,
        "source_system": source_system,
        "external_customer_id": str(
            values.get("external_customer_id") or ""
        ).strip(),
        "is_imported": True,
        "import_batch_id": str(batch_id),
        "exclude_from_kpis": True,
    }


def _find_customer(business, payload):
    source_system = payload.get("source_system") or ""
    external_id = payload.get("external_customer_id") or ""
    email = payload.get("email") or ""
    phone = normalize_phone(payload.get("phone"))
    name = payload.get("name") or ""
    address = payload.get("service_address") or ""

    if source_system and external_id:
        customer = BusinessCustomer.objects.filter(
            business=business,
            source_system__iexact=source_system,
            external_customer_id=external_id,
        ).first()
        if customer:
            return customer, "external_customer_id"

    if email:
        customer = BusinessCustomer.objects.filter(
            business=business,
            email__iexact=email,
        ).first()
        if customer:
            return customer, "email"

    if phone:
        customer = BusinessCustomer.objects.filter(
            business=business,
            normalized_phone=phone,
        ).first()
        if customer:
            return customer, "phone"

    if name and address:
        customer = BusinessCustomer.objects.filter(
            business=business,
            name__iexact=name,
            service_address__iexact=address,
        ).first()
        if customer:
            return customer, "name_and_address"

    return None, "new"


def _upsert_customer(business, actor, values, source_system, batch_id):
    payload = _customer_payload(values, source_system, batch_id)
    customer, matched_by = _find_customer(business, payload)

    if customer:
        for field, value in payload.items():
            if value not in ("", None, []):
                setattr(customer, field, value)
        customer.updated_by = actor
        customer.save()
        return customer, True, matched_by

    customer = BusinessCustomer.objects.create(
        business=business,
        created_by=actor,
        updated_by=actor,
        **payload,
    )
    return customer, False, "new"


def _ticket_status(value):
    raw = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "OPEN": Ticket.Status.NEW,
        "NEW": Ticket.Status.NEW,
        "ASSIGNED": Ticket.Status.ASSIGNED,
        "ACCEPTED": Ticket.Status.ACCEPTED,
        "SCHEDULED": Ticket.Status.SCHEDULED,
        "IN_PROGRESS": Ticket.Status.IN_PROGRESS,
        "COMPLETE": Ticket.Status.COMPLETED,
        "COMPLETED": Ticket.Status.COMPLETED,
        "CLOSED": Ticket.Status.CLOSED,
        "INVOICED": Ticket.Status.INVOICED,
        "PAID": Ticket.Status.PAID,
        "CANCELLED": Ticket.Status.CANCELLED,
        "CANCELED": Ticket.Status.CANCELLED,
    }
    return aliases.get(raw, Ticket.Status.NEW)


def _payment_method(value):
    raw = str(value or "").strip().upper()
    aliases = {
        "CARD": Ticket.PaymentMethod.CARD,
        "CREDIT_CARD": Ticket.PaymentMethod.CARD,
        "DEBIT_CARD": Ticket.PaymentMethod.CARD,
        "CASH": Ticket.PaymentMethod.CASH,
        "CHECK": Ticket.PaymentMethod.OTHER,
        "ACH": Ticket.PaymentMethod.OTHER,
        "BANK": Ticket.PaymentMethod.OTHER,
        "OTHER": Ticket.PaymentMethod.OTHER,
    }
    return aliases.get(raw, Ticket.PaymentMethod.OTHER)


def _category(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    return ServiceCategory.objects.filter(
        Q(key__iexact=raw) | Q(name__iexact=raw),
        is_active=True,
    ).order_by("-parent_id", "id").first()


def _update_customer_history(customer, ticket):
    service_date = (
        ticket.completed_at
        or ticket.scheduled_at
        or ticket.original_created_at
        or ticket.created_at
    )
    if not customer.first_service_at or (
        service_date and service_date < customer.first_service_at
    ):
        customer.first_service_at = service_date
    if not customer.last_service_at or (
        service_date and service_date > customer.last_service_at
    ):
        customer.last_service_at = service_date
        customer.last_ticket = ticket

    customer.ticket_count += 1
    customer.lifetime_revenue_cents += int(ticket.total_amount_cents or 0)

    if ticket.status in {
        Ticket.Status.COMPLETED,
        Ticket.Status.CLOSED,
        Ticket.Status.INVOICED,
        Ticket.Status.PAID,
    }:
        customer.completed_ticket_count += 1
    if ticket.status == Ticket.Status.CANCELLED:
        customer.cancelled_ticket_count += 1

    customer.save()


class BusinessDataImportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BusinessDataImportSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        business, _, _ = _business_context(self.request)
        return BusinessDataImport.objects.filter(
            business=business,
        ).select_related("business", "created_by")

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        business, _, _ = _business_context(request)

        import_type = str(
            request.data.get("import_type") or ""
        ).strip().upper()
        valid_types = dict(BusinessDataImport.ImportType.choices)
        if import_type not in valid_types:
            raise ValidationError(
                {"import_type": "Use CUSTOMERS or TICKETS."}
            )

        file_obj = request.FILES.get("file")
        headers, rows = _read_rows(file_obj)
        mapping = _build_mapping(
            headers,
            _parse_mapping(request.data.get("column_mapping")),
        )

        results = [
            _validate_row(row_number, row, mapping, import_type)
            for row_number, row in rows
        ]
        errors = [
            {"row": result["row"], "errors": result["errors"]}
            for result in results
            if result["errors"]
        ]
        valid_rows = len(results) - len(errors)
        ready = valid_rows > 0 and not errors

        batch = BusinessDataImport.objects.create(
            business=business,
            import_type=import_type,
            status=(
                BusinessDataImport.Status.READY
                if ready
                else BusinessDataImport.Status.PREVIEWED
            ),
            source_system=str(
                request.data.get("source_system") or ""
            ).strip(),
            original_filename=str(
                getattr(file_obj, "name", "") or ""
            ),
            file_size_bytes=int(getattr(file_obj, "size", 0) or 0),
            column_mapping=mapping,
            headers=headers,
            sample_rows=results[:MAX_SAMPLE_ROWS],
            payload_rows=results if ready else [],
            total_rows=len(results),
            valid_rows=valid_rows,
            skipped_rows=len(errors),
            error_count=len(errors),
            errors=errors[:MAX_REPORTED_ERRORS],
            summary={
                "ready_to_import": ready,
                "supported_format": "CSV",
                "row_limit": MAX_IMPORT_ROWS,
                "detected_columns": sum(
                    1 for value in mapping.values() if value
                ),
                "required_next_step": (
                    "Execute this validated batch with confirm=true."
                    if ready
                    else "Correct the reported rows or column mapping."
                ),
            },
            created_by=request.user,
        )

        return Response(
            self.get_serializer(batch).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="revalidate")
    def revalidate(self, request, pk=None):
        batch = self.get_object()
        return Response(
            {
                "detail": (
                    "Re-upload the corrected CSV to create a new preview batch."
                ),
                "batch_id": str(batch.id),
                "status": batch.status,
            }
        )

    @action(detail=True, methods=["post"], url_path="execute")
    def execute(self, request, pk=None):
        batch = self.get_object()
        business, _, _ = _business_context(request)

        confirm = str(request.data.get("confirm") or "").strip().lower()
        if confirm not in {"1", "true", "yes"}:
            raise ValidationError(
                {"confirm": "Set confirm=true to execute this import."}
            )

        if batch.business_id != business.id:
            return Response(
                {"detail": "Import batch belongs to another business."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if batch.status != BusinessDataImport.Status.READY:
            raise ValidationError(
                {
                    "status": (
                        "Only READY import batches can be executed. "
                        f"Current status: {batch.status}."
                    )
                }
            )

        rows = list(batch.payload_rows or [])
        if not rows or len(rows) != batch.valid_rows:
            batch.status = BusinessDataImport.Status.FAILED
            batch.errors = [
                {
                    "row": None,
                    "errors": [
                        "Validated payload is missing. Create a new preview batch."
                    ],
                }
            ]
            batch.error_count = 1
            batch.completed_at = timezone.now()
            batch.save(
                update_fields=[
                    "status",
                    "errors",
                    "error_count",
                    "completed_at",
                ]
            )
            return Response(
                self.get_serializer(batch).data,
                status=status.HTTP_409_CONFLICT,
            )

        batch.status = BusinessDataImport.Status.PROCESSING
        batch.save(update_fields=["status"])

        imported = 0
        matched = 0
        skipped = 0
        runtime_errors = []
        duplicate_ticket_ids = 0

        for item in rows:
            row_number = item.get("row")
            values = item.get("values") or {}

            try:
                with transaction.atomic():
                    customer, was_matched, _ = _upsert_customer(
                        business,
                        request.user,
                        values,
                        batch.source_system,
                        batch.id,
                    )
                    if was_matched:
                        matched += 1

                    if batch.import_type == BusinessDataImport.ImportType.CUSTOMERS:
                        imported += 1
                        continue

                    external_ticket_id = str(
                        values.get("external_ticket_id") or ""
                    ).strip()
                    duplicate = Ticket.objects.filter(
                        assigned_business=business,
                        source_system__iexact=batch.source_system,
                        external_ticket_id=external_ticket_id,
                    ).exists()
                    if duplicate:
                        skipped += 1
                        duplicate_ticket_ids += 1
                        continue

                    created_at = (
                        _parse_datetime_value(values.get("created_at"))
                        or timezone.now()
                    )
                    scheduled_at = _parse_datetime_value(
                        values.get("scheduled_at")
                    )
                    completed_at = _parse_datetime_value(
                        values.get("completed_at")
                    )
                    cancelled_at = _parse_datetime_value(
                        values.get("cancelled_at")
                    )
                    paid_at = _parse_datetime_value(values.get("paid_at"))
                    ticket_status = _ticket_status(values.get("status"))
                    amount_cents = _money_cents(values.get("total_amount")) or 0

                    ticket = Ticket.objects.create(
                        customer=request.user,
                        business_customer=customer,
                        assigned_business=business,
                        category=_category(values.get("category")),
                        is_marketplace=False,
                        service_address=customer.service_address,
                        service_zip=customer.service_zip[:10],
                        status=ticket_status,
                        payment_method=_payment_method(
                            values.get("payment_method")
                        ),
                        total_amount_cents=amount_cents,
                        created_at=created_at,
                        scheduled_at=scheduled_at,
                        completed_at=completed_at,
                        cancelled_at=cancelled_at,
                        paid_at=paid_at,
                        is_imported=True,
                        source_system=batch.source_system,
                        external_ticket_id=external_ticket_id,
                        import_batch_id=str(batch.id),
                        original_created_at=created_at,
                        exclude_from_operational_kpis=True,
                    )

                    _update_customer_history(customer, ticket)
                    imported += 1

            except Exception as exc:
                skipped += 1
                runtime_errors.append(
                    {
                        "row": row_number,
                        "errors": [str(exc)],
                    }
                )

        batch.imported_rows = imported
        batch.matched_rows = matched
        batch.skipped_rows = skipped
        batch.error_count = len(runtime_errors)
        batch.errors = runtime_errors[:MAX_REPORTED_ERRORS]
        batch.status = (
            BusinessDataImport.Status.COMPLETED_WITH_ERRORS
            if runtime_errors
            else BusinessDataImport.Status.COMPLETED
        )
        batch.completed_at = timezone.now()
        batch.payload_rows = []
        batch.summary = {
            **(batch.summary or {}),
            "ready_to_import": False,
            "executed": True,
            "imported_rows": imported,
            "matched_customers": matched,
            "skipped_rows": skipped,
            "duplicate_ticket_ids": duplicate_ticket_ids,
            "operational_kpis_excluded": (
                batch.import_type == BusinessDataImport.ImportType.TICKETS
            ),
        }
        batch.save()

        return Response(self.get_serializer(batch).data)
