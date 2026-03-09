# backend/user_accounts/api/pm_rent_b2.py
from decimal import Decimal, ROUND_HALF_UP
from typing import List

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models.pm_rent import (
    PMRentCharge,
    PMRentPayment,
    PMRentPaymentAllocation,
)

# If your project already has these, keep them consistent:
# - X-Business-Id header scoping
# - _ensure_business_access helper
#
# We'll try to import, but also provide a safe fallback so this file runs.
try:
    from user_accounts.api.permissions import _ensure_business_access  # type: ignore
except Exception:
    _ensure_business_access = None  # fallback below


def _get_business_id(request) -> int:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    try:
        return int(raw)
    except Exception:
        return 0


def _require_business_access(request, business_id: int):
    if not business_id:
        raise serializers.ValidationError({"detail": "Missing or invalid X-Business-Id header."})

    if _ensure_business_access:
        _ensure_business_access(request.user, business_id)
        return

    # Fallback: if your helper import path differs, we fail loudly but clearly.
    raise serializers.ValidationError(
        {
            "detail": "Business access helper not found. Ensure _ensure_business_access is importable "
                      "or update pm_rent_b2.py import path."
        }
    )


MONEY_Q = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return (x or Decimal("0.00")).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


class AllocationInputSerializer(serializers.Serializer):
    charge_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class PaymentRecordSerializer(serializers.Serializer):
    tenant = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    method = serializers.CharField(required=False, allow_blank=True, default="")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    paid_at = serializers.DateTimeField(required=False)

    # Optional manual allocations
    allocations = AllocationInputSerializer(many=True, required=False)

    def validate_amount(self, value):
        if value is None:
            raise serializers.ValidationError("Amount is required.")
        if Decimal(value) <= Decimal("0.00"):
            raise serializers.ValidationError("Amount must be greater than 0.")
        return q2(Decimal(value))

    def validate(self, attrs):
        allocations = attrs.get("allocations") or []
        amt = q2(Decimal(attrs["amount"]))

        if allocations:
            total = q2(sum(q2(Decimal(a["amount"])) for a in allocations))
            if total != amt:
                raise serializers.ValidationError(
                    {"allocations": f"Allocation total {total} must equal payment amount {amt}."}
                )
            for a in allocations:
                if Decimal(a["amount"]) <= Decimal("0.00"):
                    raise serializers.ValidationError({"allocations": "Allocation amounts must be > 0."})
        return attrs


class ChargeAdjustSerializer(serializers.Serializer):
    tenant = serializers.IntegerField()
    property = serializers.IntegerField()
    unit = serializers.IntegerField()
    due_date = serializers.DateField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    charge_type = serializers.ChoiceField(choices=[PMRentCharge.ChargeType.CARRYOVER, PMRentCharge.ChargeType.ADJUSTMENT])
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_amount(self, value):
        if value is None:
            raise serializers.ValidationError("Amount is required.")
        # Allow negative adjustments in DB; model validators are not enforced on save().
        # This enables credits (negative) as requested.
        if Decimal(value) == Decimal("0.00"):
            raise serializers.ValidationError("Amount cannot be 0.")
        return q2(Decimal(value))


class PaymentAllocationOutSerializer(serializers.ModelSerializer):
    charge_id = serializers.IntegerField(source="charge.id")
    charge_type = serializers.CharField(source="charge.charge_type")
    due_date = serializers.DateField(source="charge.due_date")

    class Meta:
        model = PMRentPaymentAllocation
        fields = ["id", "charge_id", "charge_type", "due_date", "amount", "created_at"]


class PaymentOutSerializer(serializers.ModelSerializer):
    allocations = PaymentAllocationOutSerializer(many=True, read_only=True)

    class Meta:
        model = PMRentPayment
        fields = ["id", "business_id", "tenant_id", "charge_id", "amount", "method", "reference", "paid_at", "created_at", "allocations"]


class PMRentPaymentB2ViewSet(viewsets.ViewSet):
    """
    NEW endpoint (B2):
      POST /api/v1/pm/rent/payments/record/
      body: { tenant, amount, method, reference, paid_at?, allocations?: [{charge_id, amount}] }

    - If allocations omitted -> FIFO: oldest outstanding balances first (by due_date, id).
    - Always writes allocations (B2).
    - Recomputes impacted charges to prove running balances.
    """

    @action(detail=False, methods=["post"], url_path="record")
    def record(self, request):
        business_id = _get_business_id(request)
        _require_business_access(request, business_id)

        ser = PaymentRecordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        tenant_id = ser.validated_data["tenant"]
        amount = q2(Decimal(ser.validated_data["amount"]))
        method = ser.validated_data.get("method", "") or ""
        reference = ser.validated_data.get("reference", "") or ""
        paid_at = ser.validated_data.get("paid_at") or timezone.now()
        allocations_in = ser.validated_data.get("allocations") or []

        with transaction.atomic():
            payment = PMRentPayment.objects.create(
                business_id=business_id,
                tenant_id=tenant_id,
                amount=amount,
                method=method,
                reference=reference,
                paid_at=paid_at,
                charge_id=None,  # B2: allocations handle distribution; keep legacy field empty
            )

            touched_charge_ids: List[int] = []

            if allocations_in:
                # Manual allocations
                for a in allocations_in:
                    charge_id = int(a["charge_id"])
                    alloc_amt = q2(Decimal(a["amount"]))

                    charge = PMRentCharge.objects.select_for_update().filter(
                        id=charge_id,
                        business_id=business_id,
                        tenant_id=tenant_id,
                    ).first()
                    if not charge:
                        raise serializers.ValidationError({"allocations": f"Invalid charge_id {charge_id} for this tenant/business."})

                    # Can't allocate more than current outstanding (for positive-balance charges)
                    # For negative charges (credits), we allow allocation only if it reduces magnitude.
                    # Practically: we allow allocation if charge.balance != 0 (after recompute).
                    charge.recompute(save=True)

                    # For standard positive charges: alloc <= balance
                    if charge.amount >= Decimal("0.00") and charge.balance >= Decimal("0.00"):
                        if alloc_amt > charge.balance:
                            raise serializers.ValidationError({"allocations": f"Allocation {alloc_amt} exceeds charge balance {charge.balance} for charge {charge.id}."})

                    PMRentPaymentAllocation.objects.create(
                        payment=payment,
                        charge=charge,
                        amount=alloc_amt,
                    )
                    touched_charge_ids.append(charge.id)

            else:
                # FIFO auto allocation: oldest outstanding first
                remaining = amount

                # Recompute balances for candidate charges (cheap enough in SQLite; keeps correctness)
                candidates = PMRentCharge.objects.select_for_update().filter(
                    business_id=business_id,
                    tenant_id=tenant_id,
                ).order_by("due_date", "id")

                # Prefer charges with positive balance > 0
                # We'll iterate and recompute as we go.
                for ch in candidates:
                    if remaining <= Decimal("0.00"):
                        break

                    ch.recompute(save=True)
                    bal = ch.balance

                    if bal <= Decimal("0.00"):
                        continue

                    take = bal if bal <= remaining else remaining
                    take = q2(take)
                    if take <= Decimal("0.00"):
                        continue

                    PMRentPaymentAllocation.objects.create(
                        payment=payment,
                        charge=ch,
                        amount=take,
                    )
                    touched_charge_ids.append(ch.id)
                    remaining = q2(remaining - take)

                if remaining != Decimal("0.00"):
                    # If they overpaid, we keep the payment and return remaining amount unallocated.
                    # (Later you can implement "unapplied credit" as an ADJUSTMENT negative charge.)
                    pass

            # Recompute touched charges (proof of balances)
            if touched_charge_ids:
                for ch in PMRentCharge.objects.filter(id__in=set(touched_charge_ids)):
                    ch.recompute(save=True)

            out = PaymentOutSerializer(payment).data

            # Add summary
            out["summary"] = {
                "payment_amount": str(amount),
                "allocated_total": str(
                    q2(
                        PMRentPaymentAllocation.objects.filter(payment_id=payment.id).aggregate(s=models.Sum("amount"))["s"]
                        or Decimal("0.00")
                    )
                ),
            }

            return Response(out, status=status.HTTP_201_CREATED)


class PMRentChargeB2ActionsViewSet(viewsets.ViewSet):
    """
    NEW endpoint (B2):
      POST /api/v1/pm/rent/charges/adjust/
      body: { tenant, property, unit, due_date?, amount, charge_type: CARRYOVER|ADJUSTMENT, notes, description }

    - Creates a standalone charge line item.
    - Supports property takeover carryover (ex: +704).
    - Supports adjustments (positive or negative).
    """

    @action(detail=False, methods=["post"], url_path="adjust")
    def adjust(self, request):
        business_id = _get_business_id(request)
        _require_business_access(request, business_id)

        ser = ChargeAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        tenant_id = ser.validated_data["tenant"]
        property_id = ser.validated_data["property"]
        unit_id = ser.validated_data["unit"]
        due_date = ser.validated_data.get("due_date") or timezone.localdate()
        amount = q2(Decimal(ser.validated_data["amount"]))
        charge_type = ser.validated_data["charge_type"]
        notes = ser.validated_data.get("notes", "") or ""
        description = ser.validated_data.get("description", "") or ""

        with transaction.atomic():
            ch = PMRentCharge.objects.create(
                business_id=business_id,
                tenant_id=tenant_id,
                property_id=property_id,
                unit_id=unit_id,
                due_date=due_date,
                charge_type=charge_type,
                amount=amount,
                notes=notes,
                description=description,
                related_charge_id=None,
            )
            ch.recompute(save=True)

        return Response(
            {
                "id": ch.id,
                "business_id": ch.business_id,
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
            status=status.HTTP_201_CREATED,
        )
