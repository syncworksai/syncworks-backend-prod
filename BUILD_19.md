# Build 19 — Customer Invoice Payment Loop

This build connects the Business Invoice Center to a customer-facing payment experience without replacing the existing Invoice, InvoiceLineItem, Stripe, ticket, platform-fee, or affiliate commission engines.

## Flow

Completed job → Business draft invoice → Business sends invoice → customer Billing notification → customer Invoice Center → secure Stripe checkout for remaining balance → webhook marks invoice/ticket paid → platform fee and affiliate commission recording → customer payment confirmation.

## Guardrails

- Draft invoices are not visible to customers and cannot be paid.
- Partial payments reduce Stripe checkout to the remaining balance.
- External payments remain reconciliation events and are not represented as SyncWorks-processed payments.
- Customer invoice queries are scoped to the authenticated ticket customer.
- Business invoice management remains scoped by Business owner/team finance permissions.
