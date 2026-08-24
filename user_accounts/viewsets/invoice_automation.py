from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, Invoice, InvoiceAutomationSettings


def _business_context(request):
    raw = request.headers.get("X-Business-Id") or request.query_params.get("business_id")
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


def _can_manage(business, member, user):
    return bool(business.owner_id == user.id or (member and (member.can_manage_invoices or member.can_manage_settings)))


def _settings_payload(settings):
    return {
        "auto_send_invoices": settings.auto_send_invoices,
        "due_terms": settings.due_terms,
        "custom_due_days": settings.custom_due_days,
        "due_days": settings.due_days(),
        "auto_reminders_enabled": settings.auto_reminders_enabled,
        "reminder_before_due_days": settings.reminder_before_due_days,
        "reminder_on_due_date": settings.reminder_on_due_date,
        "reminder_after_due_days": settings.reminder_after_due_days,
        "pause_new_non_emergency_work_when_overdue": settings.pause_new_non_emergency_work_when_overdue,
        "overdue_pause_threshold_days": settings.overdue_pause_threshold_days,
        "overdue_pause_threshold_cents": settings.overdue_pause_threshold_cents,
    }


class BusinessInvoiceAutomationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _business_context(request)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage(business, member, request.user):
            return Response({"detail": "Invoice or settings permission required."}, status=403)
        settings, _ = InvoiceAutomationSettings.objects.get_or_create(business=business)
        return Response({"business_id": business.id, "business_name": business.name, **_settings_payload(settings)})

    def patch(self, request):
        try:
            business, member = _business_context(request)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage(business, member, request.user):
            return Response({"detail": "Invoice or settings permission required."}, status=403)

        settings, _ = InvoiceAutomationSettings.objects.get_or_create(business=business)
        booleans = ["auto_send_invoices", "auto_reminders_enabled", "reminder_on_due_date", "pause_new_non_emergency_work_when_overdue"]
        integers = ["custom_due_days", "reminder_before_due_days", "overdue_pause_threshold_days", "overdue_pause_threshold_cents"]
        for field in booleans:
            if field in request.data:
                setattr(settings, field, bool(request.data.get(field)))
        for field in integers:
            if field in request.data:
                try:
                    setattr(settings, field, max(0, int(request.data.get(field))))
                except (TypeError, ValueError):
                    return Response({"detail": f"{field} must be a non-negative number."}, status=400)
        if "due_terms" in request.data:
            value = str(request.data.get("due_terms") or "").upper()
            allowed = {choice[0] for choice in InvoiceAutomationSettings.DueTerms.choices}
            if value not in allowed:
                return Response({"detail": "Invalid due terms."}, status=400)
            settings.due_terms = value
        if "reminder_after_due_days" in request.data:
            raw = request.data.get("reminder_after_due_days") or []
            if not isinstance(raw, list):
                return Response({"detail": "reminder_after_due_days must be a list."}, status=400)
            try:
                settings.reminder_after_due_days = sorted({max(0, int(value)) for value in raw})[:12]
            except (TypeError, ValueError):
                return Response({"detail": "Reminder days must be whole numbers."}, status=400)
        settings.save()
        return Response({"business_id": business.id, "business_name": business.name, **_settings_payload(settings)})


class BusinessReceivablesIntelligenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _business_context(request)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage(business, member, request.user):
            return Response({"detail": "Financial access required."}, status=403)

        today = timezone.localdate()
        invoices = Invoice.objects.select_related("ticket", "ticket__customer").filter(ticket__assigned_business=business).exclude(status=Invoice.Status.VOID)
        buckets = {"current": Decimal("0.00"), "1_30": Decimal("0.00"), "31_60": Decimal("0.00"), "61_90": Decimal("0.00"), "90_plus": Decimal("0.00")}
        overdue_customers = {}
        for invoice in invoices:
            balance = max(Decimal("0.00"), Decimal(str(invoice.total or 0)) - Decimal(str(invoice.amount_paid or 0)))
            if balance <= 0 or invoice.status == Invoice.Status.PAID:
                continue
            days = 0
            if invoice.due_date and invoice.due_date < today:
                days = (today - invoice.due_date).days
            key = "current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
            buckets[key] += balance
            if days > 0 and invoice.ticket_id:
                customer = invoice.ticket.customer
                cid = customer.id
                row = overdue_customers.setdefault(cid, {"customer_id": cid, "customer_name": customer.get_full_name() or customer.email, "overdue_balance": Decimal("0.00"), "oldest_days": 0, "invoice_count": 0})
                row["overdue_balance"] += balance
                row["oldest_days"] = max(row["oldest_days"], days)
                row["invoice_count"] += 1

        settings, _ = InvoiceAutomationSettings.objects.get_or_create(business=business)
        customers = sorted(overdue_customers.values(), key=lambda row: (row["oldest_days"], row["overdue_balance"]), reverse=True)
        for row in customers:
            row["overdue_balance"] = str(row["overdue_balance"].quantize(Decimal("0.01")))
            threshold_amount = Decimal(settings.overdue_pause_threshold_cents) / Decimal("100")
            row["pause_recommended"] = bool(settings.pause_new_non_emergency_work_when_overdue and row["oldest_days"] >= settings.overdue_pause_threshold_days and Decimal(row["overdue_balance"]) >= threshold_amount)

        total_overdue = sum((Decimal(row["overdue_balance"]) for row in customers), Decimal("0.00"))
        return Response({
            "business_id": business.id,
            "aging": {key: str(value.quantize(Decimal("0.01"))) for key, value in buckets.items()},
            "overdue_total": str(total_overdue.quantize(Decimal("0.01"))),
            "overdue_customer_count": len(customers),
            "customers": customers[:50],
            "settings": _settings_payload(settings),
        })
