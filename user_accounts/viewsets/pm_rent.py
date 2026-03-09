# backend/user_accounts/viewsets/pm_rent.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, List

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ViewSet

from user_accounts.models import (
    Business,
    BusinessMember,
    PMBillingSettings,
    PMProperty,
    PMRentCharge,
    PMRentPayment,
    PMRentPaymentAllocation,
    PMTenant,
    PMUnit,
)
from user_accounts.serializers.pm_rent import (
    PMBillingSettingsSerializer,
    PMRentChargeSerializer,
    PMRentPaymentSerializer,
)

import stripe


# -----------------------------
# Helpers
# -----------------------------
def _biz_id_from_request(request) -> int | None:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    try:
        return int(raw) if raw else None
    except Exception:
        return None


def _require_biz_id(request) -> int:
    biz_id = _biz_id_from_request(request)
    if not biz_id:
        raise ValidationError({"detail": "X-Business-Id header is required."})
    return biz_id


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))


def _role_is(user, *roles: str) -> bool:
    r = (getattr(user, "role", "") or "").upper()
    return r in {x.upper() for x in roles}


def _ensure_business_access(request, business_id: int):
    """
    Mirrors your existing multi-tenant pattern:
    - Platform admin: allowed
    - Business owner (SBO + owner_id): allowed
    - Active BusinessMember: allowed
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if _is_platform_admin(user):
        return

    biz = Business.objects.filter(id=business_id, is_active=True).first()
    if not biz:
        raise PermissionDenied("You do not have access to this business.")

    if _role_is(user, "SBO") and getattr(biz, "owner_id", None) == getattr(user, "id", None):
        return

    is_member = BusinessMember.objects.filter(
        user_id=user.id,
        business_id=business_id,
        is_active=True,
    ).exists()

    if not is_member:
        raise PermissionDenied("You are not a member of this business.")


def _platform_base() -> str:
    return str(getattr(settings, "PLATFORM_BASE_URL", "http://localhost:5174")).rstrip("/")


def _send_email(
    to_email: str,
    subject: str,
    body: str,
    cc_email: str | None = None,
    from_email: str | None = None,
):
    if not to_email:
        return

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        to=[to_email],
        cc=[cc_email] if cc_email else None,
    )
    msg.send(fail_silently=True)


def _money(v: Any) -> Decimal:
    try:
        d = Decimal(str(v))
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _q2(x: Decimal) -> Decimal:
    return (x or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _as_int(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None


def _as_date(v: Any) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    try:
        if len(s) == 7 and s[4] == "-":  # YYYY-MM
            return date(int(s[0:4]), int(s[5:7]), 1)
        return date.fromisoformat(s)
    except Exception:
        return None


def _first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, months: int) -> date:
    y = d.year + ((d.month - 1 + months) // 12)
    m = ((d.month - 1 + months) % 12) + 1
    return date(y, m, 1)


def _assert_pm_fk_belongs_to_business(
    *,
    business_id: int,
    property_id: int | None,
    unit_id: int | None,
    tenant_id: int | None,
):
    if property_id is not None and not PMProperty.objects.filter(id=property_id, business_id=business_id).exists():
        raise PermissionDenied("Property does not belong to this business.")
    if unit_id is not None and not PMUnit.objects.filter(id=unit_id, business_id=business_id).exists():
        raise PermissionDenied("Unit does not belong to this business.")
    if tenant_id is not None and not PMTenant.objects.filter(id=tenant_id, business_id=business_id).exists():
        raise PermissionDenied("Tenant does not belong to this business.")


def _guess_unit_rent_amount(unit: PMUnit) -> Decimal | None:
    for attr in ("rent", "monthly_rent", "rent_amount", "market_rent", "amount"):
        if hasattr(unit, attr):
            try:
                v = getattr(unit, attr)
                if v is None:
                    continue
                amt = _money(v)
                if amt > Decimal("0.00"):
                    return amt
            except Exception:
                pass
    return None


class _AllocationIn:
    def __init__(self, charge_id: int, amount: Decimal):
        self.charge_id = charge_id
        self.amount = amount


# -----------------------------
# ViewSets
# -----------------------------
class PMBillingSettingsViewSet(ViewSet):
    """
    Router is registered at:
      router.register(r"pm/settings/billing", PMBillingSettingsViewSet, basename="pm-billing-settings")

    ✅ Use:
      GET   /api/v1/pm/settings/billing/current/
      PATCH /api/v1/pm/settings/billing/current/

    Alias (because you used /me/):
      GET   /api/v1/pm/settings/billing/me/
      PATCH /api/v1/pm/settings/billing/me/
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get", "patch"], url_path="current")
    def current(self, request):
        biz_id = _biz_id_from_request(request)
        if not biz_id:
            return Response({"detail": "X-Business-Id header required."}, status=status.HTTP_400_BAD_REQUEST)

        _ensure_business_access(request, biz_id)

        obj, _created = PMBillingSettings.objects.get_or_create(business_id=biz_id)

        if request.method.lower() == "get":
            return Response(PMBillingSettingsSerializer(obj).data)

        ser = PMBillingSettingsSerializer(obj, data=request.data or {}, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        return self.current(request)


class PMRentChargeViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMRentChargeSerializer

    def get_queryset(self):
        """
        ✅ Fix: honors query params (tenant/unit/property/charge_type/status + ordering)
        Example:
          /api/v1/pm/rent/charges/?tenant=4
        """
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        qs = (
            PMRentCharge.objects.filter(business_id=biz_id)
            .select_related("property", "unit", "tenant", "related_charge")
            .prefetch_related("legacy_payments", "allocations")
        )

        # Optional filters (query params)
        tenant_id = _as_int(self.request.query_params.get("tenant"))
        unit_id = _as_int(self.request.query_params.get("unit"))
        property_id = _as_int(self.request.query_params.get("property"))
        charge_type = (self.request.query_params.get("charge_type") or "").upper().strip()
        status_val = (self.request.query_params.get("status") or "").upper().strip()

        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        if property_id:
            qs = qs.filter(property_id=property_id)
        if charge_type:
            qs = qs.filter(charge_type=charge_type)
        if status_val:
            qs = qs.filter(status=status_val)

        # Ordering support (safe whitelist)
        ordering = (self.request.query_params.get("ordering") or "").strip()
        allowed = {"due_date", "-due_date", "id", "-id", "created_at", "-created_at"}
        if ordering and ordering in allowed:
            qs = qs.order_by(ordering, "-id")
        else:
            qs = qs.order_by("-due_date", "-id")

        return qs

    def perform_create(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        with transaction.atomic():
            vd = getattr(serializer, "validated_data", {}) or {}

            prop = vd.get("property")
            unit = vd.get("unit")
            tenant = vd.get("tenant")
            due_date_val = vd.get("due_date")

            property_id = getattr(prop, "id", None) if prop else None
            unit_id = getattr(unit, "id", None) if unit else None
            tenant_id = getattr(tenant, "id", None) if tenant else None

            if not property_id:
                raise ValidationError({"property": ["This field is required."]})
            if not unit_id:
                raise ValidationError({"unit": ["This field is required."]})
            if not tenant_id:
                raise ValidationError({"tenant": ["This field is required."]})
            if not due_date_val:
                raise ValidationError({"due_date": ["This field is required."]})

            _assert_pm_fk_belongs_to_business(
                business_id=biz_id,
                property_id=property_id,
                unit_id=unit_id,
                tenant_id=tenant_id,
            )

            # Prevent duplicate RENT charges for same due date/unit/tenant
            if PMRentCharge.objects.filter(
                business_id=biz_id,
                unit_id=unit_id,
                tenant_id=tenant_id,
                due_date=due_date_val,
                charge_type=PMRentCharge.ChargeType.RENT,
            ).exists():
                raise ValidationError({"detail": "Duplicate RENT charge already exists for this tenant/unit/due_date."})

            try:
                obj: PMRentCharge = serializer.save(
                    business_id=biz_id,
                    charge_type=PMRentCharge.ChargeType.RENT,
                )
            except IntegrityError:
                raise ValidationError({"detail": "Duplicate charge already exists for this tenant/unit/due_date/type."})

            obj.recompute(save=True)

    def perform_update(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        with transaction.atomic():
            obj_existing: PMRentCharge = self.get_object()
            if obj_existing.business_id != biz_id:
                raise PermissionDenied("Charge does not belong to this business.")

            vd = getattr(serializer, "validated_data", {}) or {}

            prop = vd.get("property", None)
            unit = vd.get("unit", None)
            tenant = vd.get("tenant", None)
            due_date_val = vd.get("due_date", None)

            property_id = getattr(prop, "id", None) if prop else obj_existing.property_id
            unit_id = getattr(unit, "id", None) if unit else obj_existing.unit_id
            tenant_id = getattr(tenant, "id", None) if tenant else obj_existing.tenant_id
            due_date_final = due_date_val if due_date_val else obj_existing.due_date

            _assert_pm_fk_belongs_to_business(
                business_id=biz_id,
                property_id=property_id,
                unit_id=unit_id,
                tenant_id=tenant_id,
            )

            dup_qs = (
                PMRentCharge.objects.filter(
                    business_id=biz_id,
                    unit_id=unit_id,
                    tenant_id=tenant_id,
                    due_date=due_date_final,
                    charge_type=obj_existing.charge_type,
                ).exclude(id=obj_existing.id)
            )
            if dup_qs.exists():
                raise ValidationError({"detail": "Duplicate charge would be created by this update."})

            try:
                obj: PMRentCharge = serializer.save(business_id=biz_id)
            except IntegrityError:
                raise ValidationError({"detail": "Duplicate charge would be created by this update."})

            obj.recompute(save=True)

    # -----------------------------
    # Adjust / Carryover endpoint
    # POST /api/v1/pm/rent/charges/adjust/
    # -----------------------------
    @action(detail=False, methods=["post"], url_path="adjust")
    def adjust(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        data = request.data or {}

        tenant_id = _as_int(data.get("tenant"))
        property_id = _as_int(data.get("property"))
        unit_id = _as_int(data.get("unit"))
        due = _as_date(data.get("due_date")) or timezone.localdate()
        amount = _money(data.get("amount"))
        charge_type = str(data.get("charge_type") or "").upper().strip()
        notes = str(data.get("notes") or "").strip()
        description = str(data.get("description") or "").strip()

        if not tenant_id or not property_id or not unit_id:
            raise ValidationError({"detail": "tenant, property, and unit are required."})
        if amount == Decimal("0.00"):
            raise ValidationError({"detail": "amount cannot be 0."})
        if charge_type not in {PMRentCharge.ChargeType.CARRYOVER, PMRentCharge.ChargeType.ADJUSTMENT}:
            raise ValidationError({"detail": "charge_type must be CARRYOVER or ADJUSTMENT."})

        _assert_pm_fk_belongs_to_business(
            business_id=biz_id,
            property_id=property_id,
            unit_id=unit_id,
            tenant_id=tenant_id,
        )

        with transaction.atomic():
            ch = PMRentCharge.objects.create(
                business_id=biz_id,
                property_id=property_id,
                unit_id=unit_id,
                tenant_id=tenant_id,
                due_date=due,
                charge_type=charge_type,
                amount=amount,
                description=description,
                notes=notes,
            )
            ch.recompute(save=True)

        return Response(
            {
                "ok": True,
                "charge": {
                    "id": ch.id,
                    "tenant_id": ch.tenant_id,
                    "property_id": ch.property_id,
                    "unit_id": ch.unit_id,
                    "due_date": str(ch.due_date),
                    "charge_type": ch.charge_type,
                    "amount": str(ch.amount),
                    "total_paid": str(ch.total_paid),
                    "balance": str(ch.balance),
                    "status": ch.status,
                    "description": ch.description,
                    "notes": ch.notes,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    # -----------------------------
    # Bulk generate monthly charges
    # POST /api/v1/pm/rent/charges/generate_monthly/
    # -----------------------------
    @action(detail=False, methods=["post"], url_path="generate_monthly")
    def generate_monthly(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        data = request.data or {}

        if data.get("start_month") and _as_date(data.get("start_month")) is None:
            raise ValidationError({"start_month": "Invalid date format. Use YYYY-MM or YYYY-MM-DD."})

        start_month = _as_date(data.get("start_month")) or _first_of_month(timezone.localdate())
        start_month = _first_of_month(start_month)

        months = _as_int(data.get("months")) or 1
        if months < 1 or months > 36:
            raise ValidationError({"months": "months must be between 1 and 36."})

        property_id = _as_int(data.get("property"))
        unit_id = _as_int(data.get("unit"))
        tenant_id = _as_int(data.get("tenant"))

        description = str(data.get("description") or "").strip()
        skip_existing = bool(data.get("skip_existing", True))

        tenants: Iterable[PMTenant]
        if tenant_id:
            _assert_pm_fk_belongs_to_business(business_id=biz_id, property_id=None, unit_id=None, tenant_id=tenant_id)
            tenants = PMTenant.objects.filter(id=tenant_id, business_id=biz_id)
        elif unit_id:
            _assert_pm_fk_belongs_to_business(business_id=biz_id, property_id=None, unit_id=unit_id, tenant_id=None)
            tenants = PMTenant.objects.filter(business_id=biz_id, unit_id=unit_id)
        else:
            tenants = PMTenant.objects.filter(business_id=biz_id)

        tenants = list(tenants)
        if not tenants:
            return Response({"ok": False, "detail": "No tenants found for the requested scope."}, status=status.HTTP_400_BAD_REQUEST)

        due_dates = [_add_months(start_month, i) for i in range(months)]
        min_due = due_dates[0]
        max_due = due_dates[-1]

        existing = set(
            PMRentCharge.objects.filter(
                business_id=biz_id,
                due_date__gte=min_due,
                due_date__lte=max_due,
                tenant_id__in=[t.id for t in tenants],
                charge_type=PMRentCharge.ChargeType.RENT,
            ).values_list("unit_id", "tenant_id", "due_date", "charge_type")
        )

        created = []
        skipped = []
        errors = []

        amt_in = data.get("amount", None)
        fixed_amt = _money(amt_in) if amt_in is not None else None

        with transaction.atomic():
            for t in tenants:
                t_property_id = property_id or getattr(t, "property_id", None)
                t_unit_id = unit_id or getattr(t, "unit_id", None)

                last_charge = None
                if not t_property_id or not t_unit_id:
                    last_charge = (
                        PMRentCharge.objects.filter(business_id=biz_id, tenant_id=t.id)
                        .order_by("-due_date", "-id")
                        .first()
                    )
                    if last_charge:
                        if not t_property_id:
                            t_property_id = last_charge.property_id
                        if not t_unit_id:
                            t_unit_id = last_charge.unit_id

                if not t_property_id or not t_unit_id:
                    errors.append({"tenant_id": t.id, "detail": "Tenant missing unit/property."})
                    continue

                _assert_pm_fk_belongs_to_business(
                    business_id=biz_id,
                    property_id=int(t_property_id),
                    unit_id=int(t_unit_id),
                    tenant_id=int(t.id),
                )

                amt = fixed_amt
                if (amt is None) or (amt <= Decimal("0.00")):
                    unit_obj = PMUnit.objects.filter(id=int(t_unit_id), business_id=biz_id).first()
                    guessed = _guess_unit_rent_amount(unit_obj) if unit_obj else None
                    amt = guessed if guessed else Decimal("0.00")

                if amt <= Decimal("0.00"):
                    if last_charge is None:
                        last_charge = (
                            PMRentCharge.objects.filter(business_id=biz_id, tenant_id=t.id, unit_id=int(t_unit_id))
                            .order_by("-due_date", "-id")
                            .first()
                        )
                    if last_charge:
                        amt = _money(getattr(last_charge, "amount", None))

                if amt <= Decimal("0.00"):
                    errors.append({"tenant_id": t.id, "detail": "amount required (or add rent field on unit)."})
                    continue

                for due in due_dates:
                    k = (int(t_unit_id), int(t.id), due, PMRentCharge.ChargeType.RENT)
                    if k in existing:
                        if skip_existing:
                            skipped.append({"tenant_id": t.id, "unit_id": int(t_unit_id), "due_date": str(due)})
                            continue
                        errors.append({"tenant_id": t.id, "unit_id": int(t_unit_id), "due_date": str(due), "detail": "duplicate exists"})
                        continue

                    try:
                        c = PMRentCharge.objects.create(
                            business_id=biz_id,
                            property_id=int(t_property_id),
                            unit_id=int(t_unit_id),
                            tenant_id=int(t.id),
                            due_date=due,
                            amount=amt,
                            charge_type=PMRentCharge.ChargeType.RENT,
                            status=PMRentCharge.Status.UNPAID,
                            description=description,
                            notes="",
                        )
                    except IntegrityError:
                        skipped.append({"tenant_id": t.id, "unit_id": int(t_unit_id), "due_date": str(due)})
                        existing.add(k)
                        continue

                    c.recompute(save=True)
                    existing.add(k)
                    created.append(
                        {"id": c.id, "tenant_id": t.id, "unit_id": int(t_unit_id), "due_date": str(due), "amount": str(c.amount)}
                    )

        return Response(
            {
                "ok": True,
                "start_month": str(start_month),
                "months": months,
                "created_count": len(created),
                "skipped_count": len(skipped),
                "error_count": len(errors),
                "created": created[:200],
                "skipped": skipped[:200],
                "errors": errors[:200],
            }
        )

    # -----------------------------
    # Legacy "record_payment" on a single charge
    # POST /api/v1/pm/rent/charges/{id}/record_payment/
    # -----------------------------
    @action(detail=True, methods=["post"], url_path="record_payment")
    def record_payment(self, request, pk=None):
        charge: PMRentCharge = self.get_object()

        amt = _money((request.data or {}).get("amount"))
        if amt <= Decimal("0.00"):
            return Response({"detail": "amount required."}, status=status.HTTP_400_BAD_REQUEST)

        method = str((request.data or {}).get("method") or "OTHER").upper()
        reference = str((request.data or {}).get("reference") or "").strip()

        paid_at_raw = (request.data or {}).get("paid_at")
        dt = None
        if paid_at_raw:
            try:
                iso = str(paid_at_raw).replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
            except Exception:
                dt = None

        with transaction.atomic():
            p = PMRentPayment.objects.create(
                business_id=charge.business_id,
                tenant_id=charge.tenant_id,
                charge=charge,  # legacy-compatible
                amount=amt,
                method=method,
                reference=reference,
                paid_at=dt or timezone.now(),
            )
            charge.recompute(save=True)

        return Response(
            {
                "ok": True,
                "payment": PMRentPaymentSerializer(p).data,
                "charge": PMRentChargeSerializer(charge).data,
            }
        )

    # -----------------------------
    # Assess late fee (creates a LATE_FEE charge linked to rent charge)
    # POST /api/v1/pm/rent/charges/{id}/assess_late_fee/
    # -----------------------------
    @action(detail=True, methods=["post"], url_path="assess_late_fee")
    def assess_late_fee(self, request, pk=None):
        rent_charge: PMRentCharge = self.get_object()
        biz_id = rent_charge.business_id

        settings_obj, _ = PMBillingSettings.objects.get_or_create(business_id=biz_id)

        existing_fee = PMRentCharge.objects.filter(
            business_id=biz_id,
            tenant_id=rent_charge.tenant_id,
            unit_id=rent_charge.unit_id,
            charge_type=PMRentCharge.ChargeType.LATE_FEE,
            related_charge_id=rent_charge.id,
        ).first()
        if existing_fee:
            existing_fee.recompute(save=True)
            rent_charge.recompute(save=True)
            return Response({"detail": "Late fee already assessed.", "late_fee": PMRentChargeSerializer(existing_fee).data})

        fee = settings_obj.calc_late_fee(rent_charge.amount or Decimal("0.00"))
        fee = _money(fee)
        if fee <= Decimal("0.00"):
            return Response({"detail": "Late fee amount is 0 per settings."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            late = PMRentCharge.objects.create(
                business_id=biz_id,
                property_id=rent_charge.property_id,
                unit_id=rent_charge.unit_id,
                tenant_id=rent_charge.tenant_id,
                due_date=timezone.localdate(),
                charge_type=PMRentCharge.ChargeType.LATE_FEE,
                related_charge=rent_charge,
                amount=fee,
                description="Late fee",
                notes="Assessed late fee",
                status=PMRentCharge.Status.UNPAID,
            )
            late.recompute(save=True)
            rent_charge.recompute(save=True)

        # ✅ IMPORTANT: PMBillingSettings model has NO cc_email field.
        # So we do NOT reference settings_obj.cc_email here.
        if getattr(settings_obj, "auto_email_enabled", False) and getattr(settings_obj, "email_send_on_late_fee", False):
            tenant = rent_charge.tenant
            to_email = getattr(tenant, "email", "") or getattr(tenant, "tenant_email", "") or ""
            from_email = getattr(settings_obj, "from_email", "") or None

            if to_email:
                subj = "Late fee assessed"
                body = (
                    f"A late fee has been assessed.\n\n"
                    f"Rent due date: {rent_charge.due_date}\n"
                    f"Rent: ${rent_charge.amount}\n"
                    f"Late fee: ${late.amount}\n"
                    f"Current rent balance: ${rent_charge.balance}\n"
                )
                _send_email(to_email, subj, body, cc_email=None, from_email=from_email)

        return Response({"ok": True, "late_fee": PMRentChargeSerializer(late).data})

    # -----------------------------
    # Stripe Checkout for a charge
    # POST /api/v1/pm/rent/charges/{id}/checkout/
    # -----------------------------
    @action(detail=True, methods=["post"], url_path="checkout")
    def checkout(self, request, pk=None):
        charge: PMRentCharge = self.get_object()

        stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not stripe.api_key:
            return Response({"detail": "STRIPE_SECRET_KEY not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        charge.recompute(save=True)
        amount_due = charge.balance or Decimal("0.00")
        if amount_due <= Decimal("0.00"):
            return Response({"detail": "Nothing due on this charge."}, status=status.HTTP_400_BAD_REQUEST)

        cents = int((amount_due * 100).quantize(Decimal("1")))

        base = _platform_base()
        success_url = f"{base}/pm?tab=rent&paid=1&charge_id={charge.id}"
        cancel_url = f"{base}/pm?tab=rent&cancel=1&charge_id={charge.id}"

        title = f"Rent Payment • Charge #{charge.id}"
        desc = f"Due {charge.due_date} • Property #{charge.property_id} • Unit #{charge.unit_id}"

        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": title, "description": desc},
                        "unit_amount": cents,
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "type": "pm_rent_charge",
                "charge_id": str(charge.id),
                "business_id": str(charge.business_id),
            },
        )

        return Response({"url": session.url, "session_id": session.id})


class PMRentPaymentViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMRentPaymentSerializer

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        return (
            PMRentPayment.objects.select_related("charge", "tenant", "charge__tenant", "charge__unit", "charge__property")
            .filter(Q(business_id=biz_id) | Q(charge__business_id=biz_id))
            .order_by("-paid_at", "-id")
        )

    def perform_create(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        with transaction.atomic():
            obj: PMRentPayment = serializer.save()

            # Ensure business + tenant are set when possible
            if obj.charge_id and getattr(obj, "business_id", 0) in (0, None):
                obj.business_id = obj.charge.business_id
            if obj.charge_id and obj.tenant_id is None:
                obj.tenant_id = obj.charge.tenant_id
            if getattr(obj, "business_id", 0) in (0, None) and obj.charge_id:
                obj.business_id = obj.charge.business_id

            obj.save(update_fields=["business_id", "tenant_id"])

            if obj.charge_id:
                obj.charge.recompute(save=True)

    # -----------------------------
    # Record payment with allocations (B2)
    # POST /api/v1/pm/rent/payments/record/
    # -----------------------------
    @action(detail=False, methods=["post"], url_path="record")
    def record(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        data = request.data or {}
        tenant_id = _as_int(data.get("tenant"))
        amount = _money(data.get("amount"))
        method = str(data.get("method") or "").upper().strip()
        reference = str(data.get("reference") or "").strip()

        if not tenant_id:
            raise ValidationError({"tenant": "tenant is required."})
        if amount <= Decimal("0.00"):
            raise ValidationError({"amount": "amount must be > 0."})

        _assert_pm_fk_belongs_to_business(business_id=biz_id, property_id=None, unit_id=None, tenant_id=tenant_id)

        paid_at_raw = data.get("paid_at")
        paid_at = None
        if paid_at_raw:
            try:
                iso = str(paid_at_raw).replace("Z", "+00:00")
                paid_at = datetime.fromisoformat(iso)
                if paid_at.tzinfo is None:
                    paid_at = timezone.make_aware(paid_at, timezone.get_current_timezone())
            except Exception:
                paid_at = None

        allocations_payload = data.get("allocations") or None
        allocations: List[_AllocationIn] = []
        if allocations_payload:
            if not isinstance(allocations_payload, list):
                raise ValidationError({"allocations": "allocations must be a list."})
            for a in allocations_payload:
                cid = _as_int((a or {}).get("charge_id"))
                amt = _money((a or {}).get("amount"))
                if not cid or amt <= Decimal("0.00"):
                    raise ValidationError({"allocations": "Each allocation requires charge_id and amount > 0."})
                allocations.append(_AllocationIn(cid, amt))

            total = _q2(sum(_q2(x.amount) for x in allocations))
            if total != _q2(amount):
                raise ValidationError({"allocations": f"Allocation total {total} must equal payment amount {_q2(amount)}."})

        with transaction.atomic():
            p = PMRentPayment.objects.create(
                business_id=biz_id,
                tenant_id=tenant_id,
                amount=amount,
                method=method or "OTHER",
                reference=reference,
                paid_at=paid_at or timezone.now(),
                charge_id=None,  # allocations drive charge linkage
            )

            touched_charge_ids: List[int] = []

            if allocations:
                # Manual allocations
                for a in allocations:
                    ch = (
                        PMRentCharge.objects.select_for_update()
                        .filter(id=a.charge_id, business_id=biz_id, tenant_id=tenant_id)
                        .first()
                    )
                    if not ch:
                        raise ValidationError({"allocations": f"Invalid charge_id {a.charge_id} for this tenant/business."})

                    ch.recompute(save=True)
                    if a.amount > (ch.balance or Decimal("0.00")):
                        raise ValidationError({"allocations": f"Allocation {a.amount} exceeds balance {ch.balance} for charge {ch.id}."})

                    PMRentPaymentAllocation.objects.create(payment=p, charge=ch, amount=_q2(a.amount))
                    touched_charge_ids.append(ch.id)

            else:
                # FIFO auto-allocation: oldest positive balances first
                remaining = _q2(amount)

                candidates = (
                    PMRentCharge.objects.select_for_update()
                    .filter(business_id=biz_id, tenant_id=tenant_id, balance__gt=Decimal("0.00"))
                    .order_by("due_date", "id")
                )

                for ch in candidates:
                    if remaining <= Decimal("0.00"):
                        break

                    ch.recompute(save=True)
                    bal = _q2(ch.balance or Decimal("0.00"))
                    if bal <= Decimal("0.00"):
                        continue

                    take = bal if bal <= remaining else remaining
                    take = _q2(take)
                    if take <= Decimal("0.00"):
                        continue

                    PMRentPaymentAllocation.objects.create(payment=p, charge=ch, amount=take)
                    touched_charge_ids.append(ch.id)
                    remaining = _q2(remaining - take)

            # Recompute touched charges
            for ch in PMRentCharge.objects.filter(id__in=set(touched_charge_ids)):
                ch.recompute(save=True)

            alloc_total = _q2(
                PMRentPaymentAllocation.objects.filter(payment_id=p.id).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            )

            return Response(
                {
                    "ok": True,
                    "payment": {
                        "id": p.id,
                        "business_id": p.business_id,
                        "tenant_id": p.tenant_id,
                        "amount": str(p.amount),
                        "method": p.method,
                        "reference": p.reference,
                        "paid_at": p.paid_at.isoformat(),
                        "allocated_total": str(alloc_total),
                        "allocations": [
                            {
                                "id": a.id,
                                "charge_id": a.charge_id,
                                "amount": str(a.amount),
                                "charge_type": a.charge.charge_type,
                                "due_date": str(a.charge.due_date),
                            }
                            for a in p.allocations.select_related("charge").all()
                        ],
                    },
                },
                status=status.HTTP_201_CREATED,
            )
