from __future__ import annotations

from decimal import Decimal

from platform_affiliates.choices import RevenueSource
from platform_affiliates.services.commission_service import (
    record_syncworks_revenue_commission,
)


def record_invoice_platform_fee_commission(invoice):
    """
    Creates affiliate commission when SyncWorks platform fee revenue is collected.

    Rules:
    - Commission is based on SyncWorks revenue only, not gross invoice GMV.
    - Invoice total = gross revenue amount.
    - Invoice platform_fee_amount = net SyncWorks revenue amount.
    - Source reference is invoice-specific to prevent duplicate commissions.
    """
    if not invoice:
        return None

    if not getattr(invoice, "platform_fee_collected", False):
        return None

    business = None
    ticket = getattr(invoice, "ticket", None)

    if ticket is not None:
        business = getattr(ticket, "business", None)

        if business is None:
            business = getattr(ticket, "assigned_business", None)

    if business is None:
        return None

    platform_fee_amount = Decimal(str(getattr(invoice, "platform_fee_amount", "0.00") or "0.00"))

    if platform_fee_amount <= Decimal("0.00"):
        return None

    source_reference = f"invoice:{invoice.id}:platform_fee"

    return record_syncworks_revenue_commission(
        business=business,
        net_syncworks_revenue_amount=platform_fee_amount,
        source_reference=source_reference,
        revenue_source=RevenueSource.PLATFORM_FEE,
        source_date=getattr(invoice, "paid_at", None).date() if getattr(invoice, "paid_at", None) else None,
        gross_revenue_amount=getattr(invoice, "total", "0.00") or "0.00",
        memo=f"Affiliate commission from Invoice #{invoice.id} platform fee.",
    )