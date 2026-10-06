from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from user_accounts.models.finance_payments import FinanceDebtPayment
from user_accounts.models.personal_finance import FinanceLiability

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _decimal(value, default=ZERO) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def estimated_interest_saved_next_30_days(amount: Decimal, apr) -> Decimal:
    apr_value = _decimal(apr)
    if amount <= ZERO or apr_value <= ZERO:
        return ZERO
    return (amount * (apr_value / Decimal("100")) * (Decimal("30") / Decimal("365"))).quantize(CENT)


@transaction.atomic
def record_manual_debt_payment(*, user, liability_id: int, amount, payment_date=None, notes: str = "") -> FinanceDebtPayment:
    liability = (
        FinanceLiability.objects.select_for_update()
        .select_related("account")
        .filter(id=liability_id, user=user)
        .first()
    )
    if liability is None:
        raise ValueError("Debt account not found.")

    payment_amount = _decimal(amount)
    if payment_amount <= ZERO:
        raise ValueError("Payment amount must be greater than zero.")

    if payment_date in (None, ""):
        paid_on = timezone.localdate()
    elif isinstance(payment_date, date):
        paid_on = payment_date
    else:
        try:
            paid_on = date.fromisoformat(str(payment_date))
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a valid payment date.") from exc

    balance_before = max(_decimal(liability.outstanding_balance), ZERO)
    principal_applied = min(payment_amount, balance_before)
    balance_after = max(ZERO, balance_before - principal_applied).quantize(CENT)
    interest_saved = estimated_interest_saved_next_30_days(principal_applied, liability.apr or liability.interest_rate)

    payment = FinanceDebtPayment.objects.create(
        user=user,
        liability=liability,
        account=liability.account,
        amount=payment_amount.quantize(CENT),
        payment_date=paid_on,
        source=FinanceDebtPayment.Source.MANUAL,
        status=FinanceDebtPayment.Status.POSTED,
        balance_before=balance_before.quantize(CENT),
        balance_after=balance_after,
        principal_amount=principal_applied.quantize(CENT),
        estimated_interest_saved_next_30_days=interest_saved,
        notes=(notes or "").strip(),
        metadata={"balance_adjustment_applied": True},
    )

    liability.outstanding_balance = balance_after
    liability.last_payment_amount = payment.amount
    liability.last_payment_date = paid_on
    metadata = dict(liability.metadata or {})
    minimum = liability.minimum_payment if liability.minimum_payment is not None else liability.next_payment_amount
    if minimum is not None and payment_amount >= _decimal(minimum):
        metadata["paid_this_cycle"] = True
    metadata["last_payment_source"] = "MANUAL"
    metadata["last_payment_ledger_id"] = payment.id
    liability.metadata = metadata
    liability.save(update_fields=[
        "outstanding_balance",
        "last_payment_amount",
        "last_payment_date",
        "metadata",
        "updated_at",
    ])

    if liability.account_id and liability.account is not None:
        liability.account.current_balance = balance_after
        account_metadata = dict(liability.account.metadata or {})
        account_metadata["last_manual_payment_ledger_id"] = payment.id
        liability.account.metadata = account_metadata
        liability.account.save(update_fields=["current_balance", "metadata", "updated_at"])

    return payment


@transaction.atomic
def record_provider_payment_snapshot(*, liability: FinanceLiability, amount, payment_date, provider_reference: str = "") -> FinanceDebtPayment | None:
    payment_amount = _decimal(amount)
    if payment_amount <= ZERO or not payment_date:
        return None

    paid_on = payment_date if isinstance(payment_date, date) else date.fromisoformat(str(payment_date))
    reference = (provider_reference or f"LIABILITY:{liability.account_id}:{paid_on.isoformat()}:{payment_amount}")[:255]

    existing = FinanceDebtPayment.objects.filter(user=liability.user, provider_reference=reference).first()
    if existing:
        return existing

    # If the user logged the same payment manually, keep one ledger row and mark it verified.
    manual_match = (
        FinanceDebtPayment.objects.filter(
            user=liability.user,
            liability=liability,
            source=FinanceDebtPayment.Source.MANUAL,
            status=FinanceDebtPayment.Status.POSTED,
            payment_date=paid_on,
            amount=payment_amount,
        )
        .order_by("-id")
        .first()
    )
    if manual_match:
        manual_match.provider_reference = reference
        metadata = dict(manual_match.metadata or {})
        metadata["provider_verified"] = True
        manual_match.metadata = metadata
        manual_match.save(update_fields=["provider_reference", "metadata", "updated_at"])
        return manual_match

    return FinanceDebtPayment.objects.create(
        user=liability.user,
        liability=liability,
        account=liability.account,
        amount=payment_amount.quantize(CENT),
        payment_date=paid_on,
        source=FinanceDebtPayment.Source.PLAID,
        status=FinanceDebtPayment.Status.POSTED,
        provider_reference=reference,
        metadata={"provider_verified": True, "balance_adjustment_applied": False},
    )
