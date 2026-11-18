# Sync Assist — Ohio scheduled worker (restricted pilot)

This is the deployment path after SW-TEST-005 proved a single manual Shell worker invocation.

## Safety invariants

- **Independent Render Cron Job in Ohio**, not a loop or thread inside the web server.
- Cron command: `bash scripts/run_sync_assist_cron.sh`
- Region: `ohio`; repository: `syncworksai/syncworks-backend-prod`, branch: `main`
- Python runtime; build: `pip install -r requirements.txt`
- Schedule: `*/5 * * * *` (Render uses UTC); at most one job per tick.
- Default OFF. Both `SYNC_ASSIST_DURABLE_WORKER_ENABLED=true` and
  `SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED=true` must be explicitly set on the CRON SERVICE.
- The cron uses Django's effective `DB_ENGINE=postgres`, `POSTGRES_DB=syncworks_db`, `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and optionally `POSTGRES_PORT` settings connected privately to **Ohio**. A `DATABASE_URL` alone is not used by this Django configuration and does not prove correctness. Never copy credentials into code, chat, GitHub or logs.
- Keep `SYNC_ASSIST_LIVE_RESEARCH_ENABLED=false` and all external sends disabled.
- Run under the existing pilot API/owner authorization gates; do not grant new external tools.
- One job max per tick; job leases and per-owner receipt deduplication remain enforced by the ORM.
- Each tick must generate `sync_assist.queue.worker_tick` evidence, including zero-job ticks.
- Require an independently verified logical backup export and PITR availability before activation.
- Do not test interruptions during Render's 2026-11-17 20:00 CST maintenance window.
- Do not enable using guessed Render environment variables or point Cron at Oregon.
- Cron service is separately billable and may incur usage charges; obtain owner's approval before provisioning.

## Rollout

1. Merge reviewed code after CI passes.
2. Create an Ohio Render Cron Job on the repository with the settings above.
3. Keep both enable flags `false`; verify healthy builds and a logged disabled tick.
4. In Render dashboard, securely configure `DB_ENGINE=postgres` and `POSTGRES_*` for the Ohio `syncworks-db` using the normal secret/environment workflow. Do not expose credentials to reviewers. The script verifies the effective Django database, the `syncworks_db` name, and required tables before processing a job.
5. Verify database recovery readiness (backup export and PITR/restore evidence) independently. Only then enable worker and scheduled flags on **the cron job only**; leave external research/messaging disabled.
6. Enroll a fresh owner-authorized internal-only SW-TEST-006 goal. Never reuse the cancelled
   SW-TEST-004 or already-`WAITING` SW-TEST-005 jobs.
7. Observe the next cron run: job `QUEUED -> WAITING`, one receipt, one worker-tick,
   `messages_sent=0`, `external_actions=0`; owner approval remains required.
8. Verify a second tick causes no duplicate receipt and that cancelled jobs remain `CANCELLED`.
9. Run controlled retry/lease recovery tests in an isolated environment before broad rollout.

## Emergency stop

Set `SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED=false` on the cron job.
Do not disable, redeploy, or delete the production web server. Existing receipts stay stored.

## Not yet proven

A successful export is not a tested restore. Production cron scheduling, deploy health,
and lease recovery must all be verified separately before claiming autonomous production readiness.
