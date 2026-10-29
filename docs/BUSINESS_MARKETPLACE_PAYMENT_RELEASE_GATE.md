# Business onboarding and marketplace payment release gate

Updated 2026-10-29. This is an engineering audit and implementation plan, not a legal opinion or an authorization to charge customers.

## Onboarding foundation

The founder-only `/platform?tab=testers` view tracks 16 manually reviewed pilot steps with server-confirmed business linkage and signup, and can send a one-time transactional completion notification on explicit founder action. Optional paid-feature offers remain **draft-only** and cannot enroll, charge, or message anyone without separate action and compliance approval.

A pilot is *not* complete solely because a prospect received an invitation or registered. Import history, authorized test jobs, mobile usability, Stripe Connect capabilities, and payment settlement must be independently verified.

## Desired customer paths

1. **Direct provider**: Customer finds a known or saved provider, filters by service/category and ZIP, reviews the provider's public booking availability, chooses a proposed appointment time, and submits a direct request. Provider accepts; server reconciles availability before marking it scheduled. Do not assume merely creating a ticket equals confirmed booking.
2. **Marketplace**: Customer has no provider; a service request is matched to appropriately eligible businesses based on service category, coverage ZIP/radius, marketplace participation, schedule, and license/qualification rules where applicable. Customer can review providers where available or receive an offer from eligible businesses. Nothing is auto-confirmed until provider accepts.
3. **Fulfillment**: Accepted → scheduled → assigned technician → work completed → approved invoice → customer reviews total and pays. Invoice and ticket status must reconcile from trusted payment webhooks, including failed payments and refunds.

Current `ServiceRequestViewSet.create` supports direct `target_business` and general marketplace mode, but complete eligibility and appointment confirmation testing is still required.

## Proposed 1% fee (NOT live)

For approved job subtotal **S**, quote a uniform SyncWorks platform-service fee `F = round_half_up(S * 0.01, cents)`.
The customer sees **S + F + applicable taxes / separately approved provider charges** before payment. This is not a card processing surcharge and must not be presented as one.

Examples (before tax):

| Service subtotal | Customer platform fee | Customer charge | Provider gross | SyncWorks gross fee |
|---|---:|---:|---:|---:|
| $100.00 | $1.00 | $101.00 | $100.00 | $1.00 |
| $250.00 | $2.50 | $252.50 | $250.00 | $2.50 |

These figures exclude Stripe processing fees, refunds, sales tax and platform costs. They are **not** platform profit. With destination charges Stripe charges the **platform** processing costs, which can exceed 1%; confirm actual contract pricing, dispute costs and economic feasibility before activating.

The pricing helper `user_accounts.services.marketplace_payment_policy.proposed_marketplace_quote` is review-only. It does **not** add invoice lines or create charges.

## Stripe Connect release plan

- Require a valid activated Stripe Express connected business with charges enabled and payouts enabled; block transaction otherwise. Never accept a raw destination ID from the browser.
- Server calculates invoice amount, tax, final customer fee, Stripe application fee in integer cents; store immutable fee breakdown and policy version on each invoice. An attempted business override of the 1% SyncWorks fee is rejected.
- In Stripe-hosted Checkout, use `payment_intent_data.transfer_data.destination = business.stripe_connect_account_id` and `payment_intent_data.application_fee_amount = F` for an approved destination-charge model. Calculate charge total as **S + F + tax** with a separately itemized platform-service-fee line. Ensure connected business gets service subtotal and applicable provider charges, not the platform fee. Actual ledger must also account for tax allocation and Stripe costs.
- Require customer to see and affirm the final transaction total, refund terms, and fee policy **after** the job is priced. A business-level one-time agreement to fee schedule can be versioned, timestamped, with identity, source, and policy hash, and retained; **it cannot replace customer consent when the final price changes**. Handle estimates and price changes explicitly.
- Capture a verified webhook event ID and Stripe payment intent/charge/application-fee/transfer identifiers; idempotently reconcile paid, partially refunded, refunded, disputed, reversed and failed states. Do not infer fee collection from invoice status.
- Reconcile and report gross job amount, customer service fee, Stripe processing expense, refunds and net provider transfer separately.
- For cash / Cash App / off-platform payments there is **no automatic Connect split**. Model separate customer-paid platform fee settlement or an explicitly accepted business collection obligation; do not claim SyncWorks collected 1% unless a real settlement entry exists. The current monthly cash-fee invoice is business-side and conflicts with the proposed all-customer-paid model.
- A provider's **additional service charge** is not an increase to SyncWorks's 1% platform fee. It must be an independent, legitimate price line item disclosed before approval, with legal/tax review. Do not permit arbitrary card-method surcharges or undisclosed added fees.

## Confirmed code gaps, 2026-10-29

- `user_accounts.viewsets.invoice_checkout.CreateInvoiceCheckoutSessionAPIView` creates a platform Checkout Session **without** `transfer_data.destination` or `application_fee_amount`. Do not claim the current checkout pays providers and collects the proposed 1%.
- `Invoice` records `platform_fee_amount` and marks it collected for card payments; that field is **not reliable evidence of an actual Connect application-fee settlement**.
- Existing cash fee invoicing currently charges the business monthly for cash transactions; this does not match the new customer-paid concept and must be replaced or explicitly segmented before rollout.
- Direct provider routing is present but needs validated service/ZIP eligibility, truthful availability and an explicit provider accept step before a booking is confirmed.
- Refund, disputes, invoice adjustments, platform-fee reversals, customer-vs-business legal merchant responsibility, tax and Stripe economics need end-to-end reconciliation.

## Legal/compliance review required before any customer-paid 1% is enabled

1. Stripe Connect marketplace terms, processor responsibility, service fee vs card surcharge classification and debit/prepaid restrictions.
2. State-by-state rules for location of customer and merchant, and Alabama sales/use tax treatment for separated fees (a platform service charge need not be classified identically to a credit-card transaction fee).
3. Consumer disclosure: prominent total payable prior to authorizing payment; approval of revised estimate/invoice, refunds and privacy terms.
4. Terms/policy acceptance: independently stored version, text/hash, UTC timestamp, authenticated actor, context; legal hold and retention policy, with re-acceptance after material fee-policy changes.
5. Feature upsell email must comply with CAN-SPAM (sender identity, address, unsubscribe and suppression). Transactional completion notice should not include an advertisement or optional upsell.
6. Existing customer records stay business-scoped. Do not email or market to their imported customer contacts from God Mode.

**Go/no-go:** No launch of customer-paid charges or payout assertions until legal/processor review and verified Stripe test-mode then small live controlled-payment flow, including refunds and fee reconciliation.
