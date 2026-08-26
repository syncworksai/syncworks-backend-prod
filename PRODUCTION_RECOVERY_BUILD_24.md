# Build 24 — Production Infrastructure & Recovery Hardening

## Purpose
Build 24 turns infrastructure/recovery from an informal checklist into an operational release gate. Source code must never claim provider-level backup, PITR, storage durability, or device behavior that it cannot prove.

## Runtime probes
- `GET /api/v1/sync-ai/health/live/` — process liveness only. No database/customer data.
- `GET /api/v1/sync-ai/health/ready/` — verifies database queryability and migration-table/schema access. Returns HTTP 503 when not ready.

These endpoints are intended for Render/Vercel uptime checks and external monitoring.

## Database backup/PITR verification
God Mode must record evidence before marking these PASSED:
1. Managed PostgreSQL automated backups are enabled.
2. Retention window is documented.
3. PITR is enabled when supported by the active provider plan.
4. Backup data is not dependent on the application instance filesystem.
5. Restore permissions/credentials are controlled and documented.

## Restore drill
A restore drill is only PASSED after:
1. Select a recent production backup/snapshot.
2. Restore it into a non-production database.
3. Run Django system checks and migration checks against the restored database.
4. Verify representative counts for users/businesses/tickets/invoices without exposing sensitive records.
5. Verify the restored environment can boot using the readiness probe.
6. Record date, backup timestamp, restore duration, operator, result, and any corrective action in God Mode Production Readiness notes.

Never test destructive restore procedures against the active production database.

## Durable uploaded media
Production uploads (business logos, ticket attachments, documents, profile media, and future generated files) must use durable provider/object storage before broad public onboarding. Local/ephemeral service filesystems are not acceptable as the only copy.

Required evidence before PASSED:
- durable storage provider/location identified
- files survive an application redeploy/restart
- access controls confirmed
- retention/versioning policy confirmed where required
- restore/retrieval test completed

## Deployment verification
Before each release certification:
- backend `main` deployment is Ready/Healthy
- frontend `main` deployment is Ready
- backend readiness probe returns 200
- frontend opens the expected production API
- current main commits match the deployed release evidence recorded in God Mode

## Mobile smoke boundary
Mobile remains PENDING until tested on a real device. CI/browser builds do not prove installed-iPhone/PWA safe areas, app switching, touch targets, native browser permission prompts, camera/file inputs, or session persistence.

## Build 25 handoff
Once Build 24 is green at the code/runtime level, Build 25 certifies the critical product lifecycle end-to-end: identity → Marketplace → Business → workforce/dispatch → completion → invoice → payment → platform fee → affiliate → notifications/SYNC.