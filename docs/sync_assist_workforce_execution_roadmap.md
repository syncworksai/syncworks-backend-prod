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

## Implemented on this branch: internal execution slice

- `POST /api/v1/sync-ai/assist/pilot/workday/<goal_uuid>/run/` executes **one**
  eligible internal action per request, using role-bound deterministic handlers.
- Research Analyst assembles up to 15 owner-entered prospects from the existing
  Growth Center audit events. Every record is explicitly `owner_entered_unverified`;
  this is NOT external research or live verification.
- Sales Manager can reuse only Research Analyst output that the owner has attested
  as completed. It surfaces existing unsent outreach drafts without messaging.
- Chief of Staff summarizes owner-attested specialist receipts.
- Each execution stores an append-only receipt containing role, step, source
  references, reported model cost, draft/output, and zero external actions.
- Blocked actions record why they could not complete; retries capped at three.
  Execution cannot mark assignments completed without an owner decision.
- `python manage.py sync_assist_workday --dry-run` previews eligible internal work.
  Actual command execution requires
  `SYNC_ASSIST_WORKDAY_INTERNAL_EXECUTION_ENABLED=true`.
  `--scheduled` also requires `SYNC_ASSIST_WORKDAY_SCHEDULER_ENABLED=true`.
  **No scheduler is provisioned by this branch.**
- The on-demand authenticated API has a bounded internal run action; it does
  not authorize network, customer messaging, purchases or payment processing.

### Important limits and follow-on engineering work

This slice uses an append-only audit log rather than a durable job queue, and
does not yet support cancellation of an in-flight distributed job, metered
model tokens, real web discovery, autonomous scheduling or SMTP delivery.
Production-scale execution still requires relational job models,
idempotency keys at the external integration boundary, a managed queue,
timeouts, cost budgets, tool permissions, provider receipts, alerting, and
isolated worker infrastructure. No claim of production-ready autonomous
execution should be made from this slice alone.
