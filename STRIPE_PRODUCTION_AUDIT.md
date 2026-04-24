# SyncWorks Stripe Production Audit

## Scope
- Subscriptions (checkout, promo/entitlements, failed payments, lock flows)
- Stripe Connect (onboarding, status, account.updated)
- Webhooks (signature validation, duplicate safety, event coverage)
- Environment/live-mode config and webhook secrets

## Architecture (current)
- **Subscription checkout/cancel APIs**: `user_accounts/viewsets/subscriptions.py`
- **Business/user billing + primary Stripe webhook**: `user_accounts/viewsets/platform_billing.py`
- **Connect onboarding/status**: `user_accounts/viewsets/stripe_connect.py`
- **Invoice payment webhook**: `user_accounts/viewsets/invoice_checkout.py`
- **PM rent webhook**: `user_accounts/viewsets/pm_rent_webhook.py`
- **Stripe env + product/live mapping**: `syncworksv7/settings.py`

## Key Risk Findings
1. **User subscription entitlement sync gap (HIGH)**
   - `checkout.session.completed` with `mode=subscription` only synced business profile path.
   - User-scoped checkout metadata (`user_id`) could complete without updating `UserBillingProfile.subscription_status`.
2. **Subscription cancel runtime error risk (HIGH)**
   - cancel flow used `timezone`-based timestamp conversion patterns that could throw in runtime paths.
3. **Webhook duplicate handling (MEDIUM)**
   - Signature validation exists.
   - Event-id persistence is not global; idempotency currently relies mostly on deterministic profile/bill updates.

## Event Coverage Review
Primary billing webhook (`StripeWebhookAPIView`) handles:
- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `account.updated`

## Connect Review
- Onboarding/account-link and status retrieval present.
- Snapshot persistence of `charges_enabled`/`payouts_enabled`/requirements present.
- `account.updated` webhook sync present.

## Env/Mode Review
- Stripe key + webhook secret gates are present.
- Live/test product ID inference/mapping implemented in settings.
- Invoice webhook secret can be dedicated (`STRIPE_INVOICE_WEBHOOK_SECRET`) with fallback.

## Hardening Changes in this PR
1. Add explicit user subscription snapshot sync helper and apply it to:
   - user-scoped `checkout.session.completed` subscription events
   - `customer.subscription.*` user profile updates by customer id
2. Harden cancel flow timestamp conversion/import path in `subscriptions.py`.
3. Add targeted tests for webhook + cancel flows.

## Remaining Operational Warnings
- Recommend adding persistent Stripe event log table for strict global idempotency if duplicate event volume increases.
- Validate webhook endpoint separation in infra (billing/connect/invoice/rent) with distinct secrets where feasible.
