# Sync Assist pilot budget and pricing policy

## Pilot: one $10/month shared AI/tool allowance
- One allowance per tenant/account across every Sync Assist employee (not $10 for each bot).
- All paid provider adapters must call `reserve_paid_tool(...max_usd=...)` before a chargeable operation.
- Reservations are serialized against the account row, idempotent per operation, and conservatively count the **upper bound**, including failed provider attempts. This is intentional safety; providers must separately enforce call size / token limits.
- A failed authorization must stop only the paid operation, **not** hide existing employee work, receipts, pending approvals, queued jobs, or manual account access.
- `GET /api/v1/sync-ai/assist/pilot/workday/jobs/` includes a `pilot_budget` summary. The number covers **only registered paid-tool reservations** and is *not* a reconciled provider bill.
- Current deterministic internal specialist actions use no LLM calls and cost $0 in registered tool reservations.
- Public paid search is disabled until its adapter can declare and reserve a bounded per-request dollar maximum; daily query limits alone do not enforce a dollar cap.
- Render Cron, Render web and database hosting, Stripe, email/phone, other apps, and future API calls bypassing this module **are not capped** by this ledger. Configure external billing alarms, provider hard caps and quota/usage reconciliation separately.
- No provider charge has been integrated with this budget yet. **Do not claim all-business spending is capped.**

## Future customer unit economics (product planning, not live billing)
- Minimum billing tier proposal: **$50/month per business**, subject to a published base bundle and actual gross-margin measurements.
- Seat pricing: Chief of Staff in base plan; optional worker roles priced separately, with a 5-worker bundle discount.
- Before selecting selling price for each role, measure cost by: provider/model, token count, tool calls, region/infrastructure, email/SMS, job duration, storage, success rate and support/refund overhead. Revenue less Stripe fees and per-customer costs should exceed a **target 70% gross margin** under realistic peak use, not just the average.
- Per-role caps should be **sub-limits of a tenant-wide cap**, never independently additive entitlements. Keep a per-customer kill switch and human ability to approve a higher allowance.
- Do not let an AI agent raise its own budget, approve an overage, or bypass provider spend controls.
- Grandfather pilot tester entitlements until commercial checkout is tested. No actual $50 price or Stripe recurring subscription is being created in this change.

## Monitoring & alerts to implement next
- Dashboard monthly reserved, remaining, per employee, last refresh, and explicit untracked costs.
- Threshold notifications (50%, 80%, 100%) for tracked reservations, with durable deduplication.
- Provider usage reconciliation and billing alert, real per-role metering and selectable caps.
- Alert owner on budget exhausted; paid actions are blocked, but free internal tasks and owner review continue.
