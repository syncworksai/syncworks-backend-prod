# backend/user_accounts/viewsets/pm_section8.py
from __future__ import annotations

import json
import re

from django.core.exceptions import FieldDoesNotExist
from django.core.mail import EmailMultiAlternatives
from django.db import models
from django.db.models import Q
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import viewsets

from user_accounts.models.pm_section8 import PMSection8Case
from user_accounts.serializers.pm_section8 import PMSection8CaseSerializer, REQUIRED_PACKET_KEYS
from user_accounts.viewsets.pm_common import get_business_from_header, require_business_access


TEXT_FIELD_TYPES = (models.CharField, models.TextField, models.EmailField)

# Frontend stores meta in notes like:
# [[SW_SECTION8_META_JSON]]{"cc_email":"someone@example.com"}
META_TAG = "[[SW_SECTION8_META_JSON]]"


def _final_field_is_text(model: type[models.Model], dotted_path: str) -> bool:
    parts = dotted_path.split("__")
    cur_model = model
    try:
        for i, part in enumerate(parts):
            f = cur_model._meta.get_field(part)
            is_last = i == len(parts) - 1
            if not is_last and getattr(f, "remote_field", None) is not None:
                cur_model = f.remote_field.model
                continue
            if is_last:
                return isinstance(f, TEXT_FIELD_TYPES)
            return False
    except FieldDoesNotExist:
        return False


def _q_icontains(model: type[models.Model], dotted_path: str, term: str) -> Q | None:
    if not _final_field_is_text(model, dotted_path):
        return None
    return Q(**{f"{dotted_path}__icontains": term})


def _normalize_packet(packet_items: dict | None) -> dict:
    src = packet_items if isinstance(packet_items, dict) else {}
    out: dict[str, bool] = {}
    # ensure required template keys exist
    for k in REQUIRED_PACKET_KEYS:
        out[k] = bool(src.get(k, False))
    # preserve any extra keys (future-proof)
    for k, v in src.items():
        if k not in out:
            out[k] = bool(v)
    return out


def _missing_keys(packet_items: dict | None) -> list[str]:
    items = _normalize_packet(packet_items)
    return [k for k in REQUIRED_PACKET_KEYS if not bool(items.get(k))]


def _extract_notes_meta(notes: str | None) -> dict:
    """
    Looks for:
      [[SW_SECTION8_META_JSON]]{"cc_email":"..."}
    and returns parsed JSON object if present.
    Safe: returns {} on any parsing issues.
    """
    if not notes:
        return {}
    idx = notes.find(META_TAG)
    if idx == -1:
        return {}

    tail = notes[idx + len(META_TAG) :].strip()
    if not tail:
        return {}

    # Prefer a clean JSON object after the tag
    m = re.match(r"^\s*(\{.*\})\s*$", tail, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return {}

    # Fallback: find first {...} block in the remainder
    m2 = re.search(r"(\{.*\})", tail, flags=re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(1))
        except Exception:
            return {}

    return {}


def _get_cc_email(obj: PMSection8Case, request) -> str | None:
    """
    CC priority:
      1) request body cc_email
      2) notes meta json cc_email
    """
    # 1) request body
    try:
        if isinstance(request.data, dict):
            body_cc = request.data.get("cc_email")
            if isinstance(body_cc, str) and "@" in body_cc:
                return body_cc.strip()
    except Exception:
        pass

    # 2) notes meta
    meta = _extract_notes_meta(getattr(obj, "notes", "") or "")
    cc = meta.get("cc_email")
    if isinstance(cc, str) and "@" in cc:
        return cc.strip()

    return None


def _send_email_with_optional_cc(
    *,
    subject: str,
    message: str,
    to_email: str,
    cc_email: str | None,
) -> None:
    """
    Uses Django email backend.
    Requires EMAIL_* settings configured (same as your current send_mail requirement).
    """
    msg = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        to=[to_email],
        cc=[cc_email] if cc_email else None,
    )
    msg.send(fail_silently=False)


def _append_note(obj: PMSection8Case, line: str) -> None:
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    base = (obj.notes or "").strip()
    entry = f"[{line} {stamp}]"
    obj.notes = (base + ("\n\n" if base else "") + entry)
    obj.save(update_fields=["notes", "updated_at"])


class PMSection8CaseViewSet(viewsets.ModelViewSet):
    """
    Section 8 case management.

    Query params:
      - q: flexible search (ONLY on text-safe fields in your schema)
      - status: ACTIVE|PENDING|SUSPENDED|TERMINATED|CLOSED
      - inspection_status: UNKNOWN|SCHEDULED|PASSED|FAILED|REINSPECTION
      - ordering: created_at, updated_at, recert_due_date, inspection_scheduled_date (prefix '-' for desc)

      ✅ packet filters:
      - packet_ready=true|false
      - missing=<key>   (ex: missing=w9)  -> returns cases missing that required packet item
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMSection8CaseSerializer

    ALLOWED_ORDER_FIELDS = {"created_at", "updated_at", "recert_due_date", "inspection_scheduled_date"}

    SEARCH_FIELDS = [
        "voucher_number",
        "hap_contract_number",
        "housing_authority_name",
        "housing_authority_phone",
        "housing_authority_email",
        "caseworker_name",
        "caseworker_phone",
        "caseworker_email",
        "notes",
        "inspection_fail_reasons",
        "tenant__first_name",
        "tenant__last_name",
        "tenant__email",
        "property__name",
        "property__address",
        "property__city",
        "property__state",
        "property__zip",
        "unit__label",
        "unit__name",
        "unit__unit_number",
    ]

    def get_queryset(self):
        biz = get_business_from_header(self.request)
        require_business_access(self.request.user, biz)

        qs = PMSection8Case.objects.filter(business=biz).select_related("property", "unit", "tenant")

        q = (self.request.query_params.get("q") or "").strip()
        status_v = (self.request.query_params.get("status") or "").strip()
        insp = (self.request.query_params.get("inspection_status") or "").strip()

        packet_ready = (self.request.query_params.get("packet_ready") or "").strip().lower()
        missing = (self.request.query_params.get("missing") or "").strip()

        if status_v:
            qs = qs.filter(status=status_v)
        if insp:
            qs = qs.filter(inspection_status=insp)

        if packet_ready in ("true", "false"):
            qs = qs.filter(packet_ready=(packet_ready == "true"))

        # ✅ Missing filter (JSONField): filter in Python using values() (avoids select_related + only() conflict)
        if missing:
            if missing not in REQUIRED_PACKET_KEYS:
                return qs.none()

            ids: list[int] = []
            for row in qs.values("id", "packet_items"):
                items = _normalize_packet(row.get("packet_items"))
                if not bool(items.get(missing)):
                    ids.append(row["id"])

            qs = qs.filter(id__in=ids)

        if q:
            if q.isdigit():
                n = int(q)
                qs = qs.filter(Q(id=n) | Q(property_id=n) | Q(unit_id=n) | Q(tenant_id=n))
            else:
                clauses: list[Q] = []
                for field_path in self.SEARCH_FIELDS:
                    qq = _q_icontains(PMSection8Case, field_path, q)
                    if qq is not None:
                        clauses.append(qq)

                if not clauses:
                    clauses = [
                        Q(voucher_number__icontains=q),
                        Q(hap_contract_number__icontains=q),
                        Q(housing_authority_name__icontains=q),
                        Q(caseworker_name__icontains=q),
                        Q(notes__icontains=q),
                        Q(inspection_fail_reasons__icontains=q),
                    ]

                big_q = clauses[0]
                for c in clauses[1:]:
                    big_q |= c
                qs = qs.filter(big_q)

        ordering = (self.request.query_params.get("ordering") or "").strip()
        if ordering:
            desc = ordering.startswith("-")
            field = ordering[1:] if desc else ordering
            if field in self.ALLOWED_ORDER_FIELDS:
                qs = qs.order_by(f"-{field}" if desc else field, "-updated_at", "-id")
            else:
                qs = qs.order_by("-updated_at", "-id")
        else:
            qs = qs.order_by("-updated_at", "-id")

        return qs

    def perform_create(self, serializer):
        biz = get_business_from_header(self.request)
        require_business_access(self.request.user, biz)

        prop = serializer.validated_data.get("property")
        unit = serializer.validated_data.get("unit")
        tenant = serializer.validated_data.get("tenant")

        if prop and getattr(prop, "business_id", None) != biz.id:
            raise ValueError("Property does not belong to this business.")
        if unit and getattr(unit, "business_id", None) != biz.id:
            raise ValueError("Unit does not belong to this business.")
        if tenant and getattr(tenant, "business_id", None) != biz.id:
            raise ValueError("Tenant does not belong to this business.")

        # Ensure packet_items always starts with the full template keys
        packet_items = serializer.validated_data.get("packet_items") or {}
        packet_items = _normalize_packet(packet_items)

        serializer.save(business=biz, created_by=self.request.user, packet_items=packet_items)

    def perform_update(self, serializer):
        # Keep packet_items normalized on update too
        packet_items = serializer.validated_data.get("packet_items")
        if packet_items is not None:
            serializer.validated_data["packet_items"] = _normalize_packet(packet_items)
        return super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def send_packet(self, request, pk=None):
        """
        POST /api/v1/pm/section8/cases/<id>/send_packet/

        ✅ Rules (matches your confirmed behavior):
          - Requires caseworker_email (agent email)
          - Requires packet checklist COMPLETE
          - Requires packet_ready=True
          - Supports CC via request body or notes meta
        """
        biz = get_business_from_header(request)
        require_business_access(request.user, biz)

        obj: PMSection8Case = self.get_object()
        if obj.business_id != biz.id:
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        to_email = (obj.caseworker_email or "").strip()
        if not to_email:
            return Response(
                {"detail": "Agent email is required (caseworker_email)."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        missing = _missing_keys(obj.packet_items)
        if missing:
            return Response(
                {"detail": "Packet is not complete.", "missing_keys": missing},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if not bool(obj.packet_ready):
            return Response(
                {"detail": "packet_ready must be true before sending final packet."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        cc_email = _get_cc_email(obj, request)

        # Record review timestamp
        obj.packet_last_reviewed_at = timezone.now()
        obj.save(update_fields=["packet_last_reviewed_at", "updated_at"])

        subject = f"Section 8 Packet Ready — Voucher {obj.voucher_number or obj.id}"
        message = (
            "Hello,\n\n"
            "A Section 8 packet is marked ready to submit.\n\n"
            f"Property: {getattr(obj, 'property_label', '') or obj.property_id}\n"
            f"Unit: {getattr(obj, 'unit_label', '') or obj.unit_id}\n"
            f"Tenant: {getattr(obj, 'tenant_label', '') or obj.tenant_id}\n"
            f"Voucher: {obj.voucher_number}\n\n"
            "Packet Checklist: COMPLETE ✅\n"
            "Packet Ready Flag: TRUE ✅\n\n"
            f"Notes:\n{obj.notes or ''}\n\n"
            "- SyncWorks PM\n"
        )

        try:
            _send_email_with_optional_cc(
                subject=subject,
                message=message,
                to_email=to_email,
                cc_email=cc_email,
            )
        except Exception as e:
            return Response(
                {"detail": f"Email failed to send. Configure EMAIL settings. Error: {str(e)}"},
                status=drf_status.HTTP_501_NOT_IMPLEMENTED,
            )

        # Track in notes (simple audit trail)
        extra = f" cc:{cc_email}" if cc_email else ""
        _append_note(obj, f"Packet sent to {to_email}{extra}")

        ser = self.get_serializer(obj)
        return Response({"ok": True, "sent_to": to_email, "cc": cc_email, "case": ser.data})

    @action(detail=True, methods=["post"])
    def send_update(self, request, pk=None):
        """
        POST /api/v1/pm/section8/cases/<id>/send_update/

        ✅ Requirements:
          - Must allow send even if packet incomplete
          - Must include missing keys in email content
          - Must support CC from frontend (request body or notes meta)
          - Logs timestamp to notes similar to send_packet
        """
        biz = get_business_from_header(request)
        require_business_access(request.user, biz)

        obj: PMSection8Case = self.get_object()
        if obj.business_id != biz.id:
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        to_email = (obj.caseworker_email or "").strip()
        if not to_email:
            return Response(
                {"detail": "Agent email is required (caseworker_email)."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        cc_email = _get_cc_email(obj, request)

        missing = _missing_keys(obj.packet_items)
        missing_lines = "\n".join([f" - {k}" for k in missing]) if missing else " - (none) ✅"

        subject = f"Section 8 Packet Update — Voucher {obj.voucher_number or obj.id}"
        message = (
            "Hello,\n\n"
            "This is a Section 8 packet STATUS UPDATE.\n"
            "The packet may still be incomplete; missing required items are listed below.\n\n"
            f"Property: {getattr(obj, 'property_label', '') or obj.property_id}\n"
            f"Unit: {getattr(obj, 'unit_label', '') or obj.unit_id}\n"
            f"Tenant: {getattr(obj, 'tenant_label', '') or obj.tenant_id}\n"
            f"Voucher: {obj.voucher_number}\n\n"
            f"Packet Ready Flag: {bool(obj.packet_ready)}\n\n"
            "Missing Required Items:\n"
            f"{missing_lines}\n\n"
            f"Notes:\n{obj.notes or ''}\n\n"
            "- SyncWorks PM\n"
        )

        try:
            _send_email_with_optional_cc(
                subject=subject,
                message=message,
                to_email=to_email,
                cc_email=cc_email,
            )
        except Exception as e:
            return Response(
                {"detail": f"Email failed to send. Configure EMAIL settings. Error: {str(e)}"},
                status=drf_status.HTTP_501_NOT_IMPLEMENTED,
            )

        extra = f" cc:{cc_email}" if cc_email else ""
        if missing:
            _append_note(obj, f"Update sent to {to_email}{extra} missing:{', '.join(missing)}")
        else:
            _append_note(obj, f"Update sent to {to_email}{extra} (required complete)")

        return Response(
            {"ok": True, "sent_to": to_email, "cc": cc_email, "missing_keys": missing},
            status=drf_status.HTTP_200_OK,
        )
