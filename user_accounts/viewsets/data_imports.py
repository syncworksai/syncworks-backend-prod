from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import BusinessDataImport
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
            {"file": "Backend 4N currently supports CSV files only."}
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
    original_headers = reader.fieldnames or []
    headers = [_clean_header(value) for value in original_headers]

    if not headers:
        raise ValidationError({"file": "CSV has no header row."})
    if len(headers) != len(set(headers)):
        raise ValidationError(
            {"file": "CSV contains duplicate column names after normalization."}
        )

    rows = []
    for row_number, source in enumerate(reader, start=2):
        if len(rows) >= MAX_IMPORT_ROWS:
            raise ValidationError(
                {"file": f"CSV exceeds the {MAX_IMPORT_ROWS}-row import limit."}
            )

        normalized = {}
        for key, value in source.items():
            normalized[_clean_header(key)] = str(value or "").strip()

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


def _money_is_valid(value):
    raw = str(value or "").replace("$", "").replace(",", "").strip()
    if not raw:
        return True
    try:
        Decimal(raw)
        return True
    except (InvalidOperation, ValueError):
        return False


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

        if not _money_is_valid(values.get("total_amount")):
            errors.append("Total amount is not a valid number.")

        for field in (
            "created_at",
            "scheduled_at",
            "completed_at",
            "cancelled_at",
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
            {
                "row": result["row"],
                "errors": result["errors"],
            }
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
                    "Review and execute this validated batch."
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
