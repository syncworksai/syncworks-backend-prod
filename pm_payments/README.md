# PM Payment Providers and Release Gates

This module is **setup and eligibility tracking only**. It never collects rent, charges a $1 fee, stores bank account numbers, accepts external processor API secrets, or asserts that a payout occurred.

## Product choices

- **STRIPE_CONNECT:** Business uses Stripe-hosted onboarding and bank verification; SyncWorks stores account ID and capabilities only. The connected business is not automatically the landlord/trust account. Link the correct legal PM portfolio and ensure the actual receiving/beneficiary account is appropriate before money movement.
- **EXTERNAL:** Store the existing processor's public provider information. This is a **manual-only** bridge; we cannot reconcile Square, PayPal, independent banks or third-party payment processors without delegated OAuth credentials, signed webhooks, import mapping and merchant consent. Do not display owner-entered URLs to tenants.
- **MANUAL:** PM ledger remains available to record bank-verified cash/check/externally received rent. No SyncWorks online payment fee is earned.

## Required contract for any payment adapter

1. Merchant onboarding, KYB/identity and bank/trust account verification, plus connection-state refresh.
2. Tenant payment request bound to **verified portfolio, lease, tenant, rental period and immutable charge snapshot**; no client-chosen receiving account.
3. Server-side rent/pricing quote: authorized rent, approved $1 SyncWorks service charge (at most one per lease-month when appropriate), actual method-specific processing costs, applicable taxes and lawful permitted fee policies.
4. Clearly disclosed, authenticated tenant authorization; alternative payment options when legally required, including Section 8/assistance restrictions and written lease terms.
5. Secure hosted checkout/payment link with expiration and unique reference; processor owns payment credentials.
6. Signature-verified idempotent events for success, ACH pending/return, failure, refund, dispute, reversal and final settlement. Never mark rent paid solely on redirect or an asynchronous ACH initiation.
7. Verified split to correct escrow/trust/PM/owner ledger. Record separately: tenant rent, tenant service fee, processor fee, actual SyncWorks net revenue, payment intent, transfer IDs and bank payout.
8. Automated due/past-due email (already partially present in pm_rent_automation), transactional notices, secure link, delivery attempts, suppression after settled and no accidental duplicate reminders.
9. A migration plan: allow existing processors to run side-by-side while reconciling actual bank receipts, support opt-in conversion and historical data import.
10. Security: per-portfolio/Business permissions, auditable actor+timestamp, encrypted secrets in credential vault only, RBAC, rate limiting and regulatory review.

## Existing gaps

The current PMWorkspace is distinct from the Business record used by Stripe Connect. DO NOT infer payout entitlement from `X-Business-Id` alone; a verified owner/legal entity and portfolio-to-business mapping are required. Multiple property owners may need multiple trust ledgers or accounts.

The legacy `PMRentChargeViewSet.checkout` created a Stripe Session on the platform without approved destination or rent fee allocation. It is explicitly blocked on this branch until replacement; existing webhook code also needs an end-to-end audit and settlement state machine.

The existing `pm_rent_automation` command generates emails, but currently doesn't provide secure tenant pay links and has not been confirmed as a scheduled production task. Backend reminders must not claim payments are complete.

The proposed $1 fee is **not guaranteed to be profit**: check processor and Connect costs against the actual payment amount and funding arrangement. Verify both property-management trust/accounting law and prohibited/limited tenant charges.

## Processor evaluations

**Stripe Connect**: fastest current implementation path; uses hosted onboarding and account-to-bank payouts. Stripe-handle-pricing vs platform-handle-pricing models differ in who pays processing, account and payout fees. Check application fee/net economics.

**Payload**: evaluate specialty rent/owner/escrow trust routing and reconciliation, hosted links, underwriting and pricing.
**Moov**: evaluate ACH/cards, managed merchant onboarding, multi-account money movement, underwriting and pricing.
**Dwolla**: evaluate ACH and bank rails for scale; tailored quotes, compliance and account ownership.
**Square/other existing processors**: preserve as external mode; create individual OAuth/webhook adapter integrations by commercial demand and documented scopes.

## Deployment

This feature intentionally never changes live rent amounts or activates new payments. Backend CI must pass migration/isolation tests. Frontend build and PM owner sign-in testing must pass before promoting. Live collections need separate reviewed PR, Stripe test-mode end-to-end payment/return/refund tests, and legal/processor approvals.
