# backend/user_accounts/models/pm_rent.py
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class PMRentCharge(models.Model):
    class ChargeType(models.TextChoices):
        RENT = "RENT", "Rent"
        LATE_FEE = "LATE_FEE", "Late fee"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        CARRYOVER = "CARRYOVER", "Carryover"

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"

    business_id = models.PositiveIntegerField(db_index=True)

    # Keep these as string refs to avoid import cycles
    property = models.ForeignKey(
        "user_accounts.PMProperty",
        on_delete=models.PROTECT,
        related_name="rent_charges",
    )
    unit = models.ForeignKey(
        "user_accounts.PMUnit",
        on_delete=models.PROTECT,
        related_name="rent_charges",
    )
    tenant = models.ForeignKey(
        "user_accounts.PMTenant",
        on_delete=models.PROTECT,
        related_name="rent_charges",
    )

    due_date = models.DateField(db_index=True)

    charge_type = models.CharField(
        max_length=20,
        choices=ChargeType.choices,
        default=ChargeType.RENT,
        db_index=True,
    )

    # Late fee links back to the rent charge (or any charge if you ever choose)
    related_charge = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="related_line_items",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    description = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
        db_index=True,
    )

    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business_id", "unit", "tenant", "due_date", "charge_type"],
                name="uniq_rent_charge_business_unit_tenant_due_type",
            )
        ]
        ordering = ["due_date", "id"]

    def __str__(self):
        return f"{self.tenant_id} {self.charge_type} {self.due_date} ${self.amount}"

    def recompute(self, save=True):
        """
        B2 logic:
        - Prefer allocations (new world)
        - Fall back to legacy direct payments on charge if there are no allocations at all
        """
        alloc_qs = PMRentPaymentAllocation.objects.filter(charge_id=self.id)
        allocated = alloc_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

        if allocated > Decimal("0.00") or alloc_qs.exists():
            paid = allocated
        else:
            # Legacy: payments directly tied to charge (nullable FK)
            paid = (
                PMRentPayment.objects.filter(charge_id=self.id)
                .aggregate(s=Sum("amount"))["s"]
                or Decimal("0.00")
            )

        bal = (self.amount or Decimal("0.00")) - paid

        if bal <= Decimal("0.00"):
            new_status = self.Status.PAID
            bal = Decimal("0.00")
        elif paid > Decimal("0.00"):
            new_status = self.Status.PARTIAL
        else:
            new_status = self.Status.UNPAID

        self.total_paid = paid
        self.balance = bal
        self.status = new_status

        if save:
            self.save(update_fields=["total_paid", "balance", "status", "updated_at"])
        return self


class PMRentPayment(models.Model):
    """
    Payment master record.

    NOTE:
    - tenant is nullable ONLY to safely migrate legacy rows that may not be tied to a charge.
    - In all new APIs we will REQUIRE tenant.
    - business_id defaults to 0 for the same legacy reason; new APIs will always set it correctly.
    """

    business_id = models.PositiveIntegerField(default=0, db_index=True)

    tenant = models.ForeignKey(
        "user_accounts.PMTenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rent_payments",
    )

    # Legacy compatibility (old flow): payment recorded “on a charge”
    charge = models.ForeignKey(
        "user_accounts.PMRentCharge",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legacy_payments",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    method = models.CharField(max_length=30, blank=True, default="")  # CASH, ACH, CARD, etc.
    reference = models.CharField(max_length=120, blank=True, default="")  # check #, stripe id, etc.

    paid_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at", "-id"]

    def __str__(self):
        return f"Payment ${self.amount} t={self.tenant_id} b={self.business_id}"


class PMRentPaymentAllocation(models.Model):
    """
    Allocation lines that apply a payment across one or more charges.
    Unique(payment, charge) so a payment has at most one row per charge.
    """

    payment = models.ForeignKey(
        "user_accounts.PMRentPayment",
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    charge = models.ForeignKey(
        "user_accounts.PMRentCharge",
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "charge"],
                name="uniq_payment_allocation_payment_charge",
            )
        ]
        ordering = ["id"]

    def __str__(self):
        return f"Alloc p={self.payment_id} c={self.charge_id} ${self.amount}"
