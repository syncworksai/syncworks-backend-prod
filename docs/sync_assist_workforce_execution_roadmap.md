# Sync Assist — workforce execution roadmap

## Product invariant

SyncWorks is the platform. Sync Assist is a permissioned workforce system that acts on
verified information and authorized tasks, not a collection of chat avatars.

## Current branch: workday foundation

- Private pilot goal and employee assignment records, isolated to authenticated owner.
- Append-only audit trail for status checkpoints.
- Explicit manual evidence and owner attestation required before completion.
- No external side effects; API advertises `execution_enabled=false`.
- Existing pilot approval API still means approval only, not execution.

Endpoints:
- `GET /api/v1/sync-ai/assist/pilot/workday/`
- `POST /api/v1/sync-ai/assist/pilot/workday/` with
  `{"goal":"...","steps":[{"role":"RESEARCH_ANALYST","task":"..."}]}`
- `POST /api/v1/sync-ai/assist/pilot/workday/<goal_uuid>/steps/<step_uuid>/`
  with `{"status":"COMPLETED","evidence":"...","owner_attested":true}`

## Next milestone: genuinely executed and verified work

1. Introduce relational `Goal`, `WorkItem`, `ExecutionAttempt`,
   `Approval`, `ToolReceipt` models with tenant-scoped access policy.
2. Define a per-action capability registry with least-privilege scopes and distinct
   read, draft, and write permissions. Never use LLM text as an authorization token.
3. Build an idempotent task queue with retries, exponential backoff, budgets,
   timeouts, cancellation, and poison-queue handling.
4. First vertical slice: Research Analyst gathers *authorized* prospect evidence,
   Sales Manager drafts a proposed outreach message, owner reviews it, sender
   uses an explicitly connected mailbox, and a receipt verifies actual delivery.
   Never auto-contact prospects without consent/approval and compliance checks.
5. Use tool receipts for `VERIFIED`; do not equate generation, approval, and external
   execution. Failed/blocked/expired tasks must remain visible.
6. Build the workforce dashboard around real states, approvals, outcomes,
   evidence links, and costs; no simulated "employees working" badges.
7. Add isolation, prompt-injection, cross-tenant, duplicate-action, secret-redaction,
   and end-to-end tests before pilot rollout.
8. Only after the first reliable workflow: calendar, customer requests, PM tasks,
   invoicing, finance summaries and additional specialized employees.

## Release gates

- Unit and integration tests green in CI.
- New endpoints verified in test/staging deployment.
- Idempotency and tenant scoping demonstrated.
- No unauthorized external sends, charges, or state changes.
- Owner can review audit trails and stop/retry any execution.
- Rollout initially private to the pilot; production activation requires a new
  explicit deployment decision after evidence is reviewed.

## Implementation notes

The audit-event workday prototype is deliberately narrow and should be replaced
by relational storage before scaling. Owner-attested completion is not the same as
a worker-verified outcome. Do not claim autonomy until an authorized worker has
executed tools and produced verifiable receipts.
