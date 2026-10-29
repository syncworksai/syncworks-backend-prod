"""Review-only proposed SyncWorks marketplace fee policy.

This module intentionally does NOT create a charge, modify invoices, transfer
funds, or turn on customer-facing fees. Production rollout requires consumer
disclosure approval, tax and card-network review, Connect integration, and
payment/refund reconciliation.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class MarketplacePaymentQuote:
    service_subtotal: Decimal
    customer_platform_fee: Decimal
    customer_total_before_tax: Decimal
    connected_business_gross: Decimal
    platform_gross_fee: Decimal


def proposed_marketplace_quote(service_subtotal, platform_fee_bps=100):
    """Cents-accurate preview of a uniform platform-service fee, never a card surcharge.

    Assumes connected business receives service subtotal through destination
    charges and platform collects customer fee as Stripe application fee.
    Does NOT model taxes, processing costs, refunds, or local requirements.
    """
    amount = Decimal(str(service_subtotal))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Service subtotal must be finite and non-negative.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Service subtotal must be expressed in cents.")
    if not isinstance(platform_fee_bps, int) or isinstance(platform_fee_bps, bool) or platform_fee_bps != 100:
        raise ValueError("Only the proposed 1% fee is supported in this review-only quote.")
    fee = (amount * Decimal(platform_fee_bps) / Decimal("10000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return MarketplacePaymentQuote(
        service_subtotal=amount, customer_platform_fee=fee,
        customer_total_before_tax=amount + fee,
        connected_business_gross=amount, platform_gross_fee=fee,
    )
