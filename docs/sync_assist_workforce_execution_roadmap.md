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

## Optional public research adapter

- Enabled **only** if the owner creates a goal with `source_mode=PUBLIC_SEARCH`,
  a separate 4–120-character `public_search_query`, and
  `allow_external_search=true`.
- Server environment must also contain `SYNC_ASSIST_LIVE_RESEARCH_ENABLED=true`
  and `SERPER_API_KEY`. These are server secrets; never put them in the frontend.
- The configured provider request is limited to a single bounded search and at
  most eight organic listings, with short timeouts and no URL crawling.
- Retrieved titles/snippets are treated as untrusted, unverified evidence,
  not verified leads, and cannot trigger external customer contact.
- No search query is derived automatically from a user's private business goal.
- Search provider costs are not currently metered in USD; model cost is reported
  as zero because no LLM is called. Before wider rollout, add provider quotas,
  spend limits, and billing metrics.

## Durable unattended worker milestone (proposed deployment)

The `SyncAssistJob` table and migration `user_accounts.0138_sync_assist_job`
persist one job per owner/goal with states QUEUED, RUNNING, WAITING, RETRY,
SUCCEEDED, FAILED and CANCELLED.

- Owner opts in via `POST /api/v1/sync-ai/assist/pilot/workday/jobs/`
  with `{"goal_id": "...", "allow_background_internal": true}`.
- Job status: `GET /api/v1/sync-ai/assist/pilot/workday/jobs/`.
- Cancel: `POST /api/v1/sync-ai/assist/pilot/workday/jobs/<goal_id>/cancel/`.
- Background task commands:
  `python manage.py sync_assist_queue_worker --dry-run` and
  `python manage.py sync_assist_queue_worker --once --max-jobs 5`.
- A separately configured Render Cron Job (or equivalent independent worker)
  must invoke `--once` at a selected cadence. The worker service must connect
  to the *same* production Postgres database as the API and run migrations first.
- Configure `SYNC_ASSIST_DURABLE_WORKER_ENABLED=true` on the **worker job
  only**, not by exposing public endpoints. Never expose DB or OAuth secrets.
- Do not configure the job before confirming the Render workspace, database,
  migration plan, backup and deployment rollback process.
- The worker refuses PUBLIC_SEARCH goals, email, payments and any third-party
  state-changing tools. These need separate, capability-restricted workers.
- Each claim records a unique lease token and expiry. Expired claims are
  reconciled; retryable failures use bounded backoff; owner-approved steps
  re-enqueue an already opted-in goal.
- One task is handled per claim. Work returns to WAITING after generating
  a receipt. Completed work requires owner attestation. Jobs can be cancelled
  through the authenticated pilot endpoint.
- The worker is **not installed, scheduled or proven active** just because
  this code is merged. Use actual service logs and persisted receipts to verify.
- Automatic in-flight cancellation is cooperative: the deterministic internal
  action may finish before the worker notices cancellation, but no external
  effects are permitted by this worker.
- For higher volumes, add separate `ExecutionAttempt` and `ToolReceipt`
  models, stronger per-action idempotency and worker heartbeats, API quotas,
  metered provider costs, and alerting.

### Verified-scheduler signal

Scheduled runs require both `SYNC_ASSIST_DURABLE_WORKER_ENABLED=true`
and `SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED=true` plus the explicit
`--scheduled` command option. Only scheduled-marked executions write
`sync_assist.queue.worker_tick` heartbeat events. The UI requires two
such events in the last 30 minutes before reporting recent worker activity.
Manual `--once` executions never count as proof of a scheduler.
