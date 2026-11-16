# SyncWorks God Mode Test Lab — controlled release specification

The Pilot Readiness UI is the release sign-off authority. Sync Assist may
*execute* test cases and attach evidence, but cannot grant privileges, mark
its own release checks PASS, or see another tester's live data.

## Test identities (staging only)

Provision at least one distinct synthetic identity per role:
Personal Free, Personal with Assist, Business owner, Employee, PM,
Tenant, Property Owner, Sales OS, Growth OS and private-pilot AI owner.
Use controlled mailboxes and two separate devices for the end-to-end
communication tests. A separate admin identity operates God Mode.

The existing `User.is_test_account` flag is the correct machine-readable
marker. Never grant test identities founder email, God Mode, or production
superuser flags. Admin-only privileges must be enforced by the server.
Do not share session tokens, passwords, invitation codes or OAuth credentials
inside test evidence.

## Entitlements and billing

Use a staging Stripe account and test-mode transactions only. Test subscriptions,
free tier, trials and each add-on by server-side explicit test entitlements,
not client-side "free forever" bypasses. Separate staging mail and webhook
credentials from production. Test users must not receive chargeable production
subscriptions, untracked permanent discounts or access to other tenants.

## Test flows

1. Personal creates a request. The correctly matched Business accepts it,
   assigns Employee and schedules work. Verify status transitions and invoice
   receipt without real card charges.
2. PM invites Tenant and Owner. Log in on independent devices and prove that
   each sees only allowed units, balances and documents. Test rejected and
   expired invite codes.
3. Business owner and Employee exchange authorized messages through test
   mailboxes. Verify sender, recipient, thread, delivery, reply, and opt-out.
4. AI owner assigns Research -> Sales -> Chief of Staff. Independent worker
   records a genuine receipt, waits for approval and resumes only when allowed.
   Test failure, cancellation, retry, duplicate claim and spending cap.
5. Attempt forbidden direct API reads and writes across each role pair.
   Check token expiry, re-authentication, device logout, recovery and rate limits.
6. Test Stripe failure/refund/webhook replay using sandbox events. No production
   billing methods or customer PII in seed fixtures.
7. Test notifications on real mobile and web devices including revocation and
   simultaneous sessions. Verify messages do not leak between accounts.
8. Perform dependency scan, secret scan, backup restore exercise, deployment
   rollback and emergency worker kill switch verification.

## Release controls

- CI passing and migration verified on branch HEAD.
- No open critical/high authorization, credential or payment vulnerabilities.
- MFA/step-up authentication for platform administrators, and verified email
  ownership for founder access, must be enforced before broad production use.
- Founder manual gates include attached, redacted, environment-specific evidence.
- Automated test reports may propose PASS but must never self-approve release.
- No unattended external actions without separate capability allowlist and
  independently verifiable tool receipts.

## Present state

This branch defines a Test Lab persona matrix and increases the required pilot
release gates. It does NOT create or fund test accounts, connect test mailboxes,
install worker cron, run cross-device sessions or certify the release.
