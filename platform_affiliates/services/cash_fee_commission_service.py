from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from platform_affiliates.choices import RevenueSource
from platform_affiliates.models import AffiliateCommissionLedger
from platform_affiliates.services.commission_service import (
    record_syncworks_revenue_commission,
)
from user_accounts.models import CashFeeInvoice


MONEY_QUANT = Decimal("0.01")


def _cents_to_money(cents: int | None) -> Decimal:
    try:
        value = Decimal(int(cents or 0)) / Decimal("100")
    except Exception:
        value = Decimal("0.00")

    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def record_cash_fee_invoice_commission(
    cash_fee_invoice: CashFeeInvoice,
) -> AffiliateCommissionLedger | None:
    """
    Creates affiliate commission when SyncWorks collects a cash/off-platform fee invoice.

    Important:
    - Affiliate is paid from SyncWorks revenue only.
    - SMB does not pay extra.
    - amount_cents is the SyncWorks fee invoice amount, so this is the net SyncWorks revenue.
    - source_reference prevents duplicate commissions.
    """
    if not cash_fee_invoice:
        return None

    if cash_fee_invoice.status != CashFeeInvoice.Status.PAID:
        return None

    business = getattr(cash_fee_invoice, "business", None)
    if business is None:
        return None

    syncworks_revenue_amount = _cents_to_money(
        getattr(cash_fee_invoice, "amount_cents", 0)
    )

    if syncworks_revenue_amount <= Decimal("0.00"):
        return None

    source_reference = f"cash_fee_invoice:{cash_fee_invoice.id}:platform_fee"

    return record_syncworks_revenue_commission(
        business=business,
        net_syncworks_revenue_amount=syncworks_revenue_amount,
        source_reference=source_reference,
        revenue_source=RevenueSource.PLATFORM_FEE,
        source_date=(
            cash_fee_invoice.paid_at.date()
            if getattr(cash_fee_invoice, "paid_at", None)
            else None
        ),
        gross_revenue_amount=Decimal("0.00"),
        memo=(
            f"Affiliate commission from Cash Fee Invoice #{cash_fee_invoice.id}. "
            "Commission is paid from SyncWorks revenue only."
        ),
    )


def record_paid_cash_fee_invoice_commissions_for_all() -> int:
    """
    Backfill/safety helper for collect-open flows.

    Scans PAID cash fee invoices and creates missing commission ledger records.
    Duplicate protection is still enforced by source_reference.
    """
    created_or_found = 0

    qs = CashFeeInvoice.objects.select_related("business").filter(
        status=CashFeeInvoice.Status.PAID,
        amount_cents__gt=0,
    )

    for inv in qs:
        before_count = AffiliateCommissionLedger.objects.count()
        commission = record_cash_fee_invoice_commission(inv)
        after_count = AffiliateCommissionLedger.objects.count()

        if commission is not None and after_count >= before_count:
            created_or_found += 1

    return created_or_found