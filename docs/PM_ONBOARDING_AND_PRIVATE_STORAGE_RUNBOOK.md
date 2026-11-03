# SyncWorks PM — End-to-end onboarding and private document storage

Status: **backend code/test foundation only**. Never treat the presence of an upload
button, a green unit test, or a configured S3 endpoint as proof of a production
file-recovery process.

## Product flow to verify

| Stage | Primary user | Inputs / proof | Required result |
| --- | --- | --- | --- |
| 1. Add property | PM/owner | property name, address, legal/management role | One property, no duplicates |
| 2. Create units | PM | unit label, availability, market rent | Unit attached to correct property |
| 3. Capture prospect | PM/leasing | inquiry, showing, application status | Prospect visible in PM leasing pipeline |
| 4. Receive application | Applicant/PM | uploaded application, consent/evidence | Tracking status + private attachment |
| 5. Approve / convert | PM | screening decision verified outside test | One tenant record, no duplicate email |
| 6. Create lease | PM/tenant | rent, due date, term, deposit, signatures | Active occupancy linked to unit |
| 7. Link files | PM | signed lease, addenda, inspection, voucher, deposit | Object stored privately; metadata in PostgreSQL |
| 8. Invite tenant | PM | recipient email, invitation code | Tenant's real email remains separate from PM |
| 9. Tenant accepts | Resident | authenticated matching-email user | One tenant portal, limited to their own home |
| 10. Rent schedule | PM | approved tenant/MHA shares, billing dates | Preview, then one charge per payer/month |
| 11. Collections | Tenant/agency/PM | processor webhook or actual manual receipt | Proper payer bucket; receipt dates preserved |
| 12. Maintenance | Resident | issue + permission to enter | Work order appears for PM |
| 13. Audit/export | PM/owner | ledger, deposit, payment and HAP evidence | Running totals match allocated receipts |
| 14. Offboarding | PM | final inspection, deposit and records | Controlled tenant access revocation, retained audit evidence |

**Automated test:** `pm_workspace.tests.test_pm_onboarding_journey` covers synthetic
property → unit → prospect/application tracking → approval → tenant →
lease/occupancy → uploaded lease → invitation → tenant portal → maintenance →
PM work orders → rent charge/payment → updated tenant balance. Existing
`test_tenant_vertical_slice` tests additional Section 8, documentary
reconciliation, late-fee review, authorization, and idempotency.

**Manual staging acceptance (not yet proved):** real browser file upload/download,
access refusal from a different tenant/PM, signed URL expiry, mobile workflow,
application consent/screening, Stripe webhooks/failed payments/refunds, invitation
email deliverability, monthly cron execution and safe replay, and full object
backup/restore.

Do **not** use Roxana's actual tenant or financial records for a mutating
end-to-end test. Create a disposable synthetic property in a non-production
workspace/database; delete only the synthetic records after verification.

## Storage choice: Cloudflare R2 (S3-compatible) for PM files

The application database stores **metadata**: document ID, owner workspace,
property, tenant, lease, category, title, file key and verified status.
Cloudflare R2 stores the encrypted file bytes. Existing code already models
`PMPropertyDocument.document` as a Django FileField. The new storage
callable selects only this FileField; it does not redirect profile photos
and other application media.

### Required environment variables on the backend service

```
PM_R2_STORAGE_ENABLED=false
PM_R2_BUCKET=<private-R2-bucket-name>
PM_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
PM_R2_ACCESS_KEY_ID=<server-secret>
PM_R2_SECRET_ACCESS_KEY=<server-secret>
PM_R2_PREFIX=pm-documents
```

All credentials are **server-only**. Never commit them or expose them to
the frontend. Enable only after an administrator has created the bucket,
restricted access keys to the relevant bucket, confirmed private access,
and validated download behavior in staging.

When enabled, file storage uses:
- non-public bucket;
- short-lived (120 second) signed GET URLs produced only after PM-scoped API
  permission checks;
- no file overwrite on same-name uploads;
- dedicated object prefix;
- encryption in transit through HTTPS.

**Do not mistake a signed link for a permanent ACL**: anybody holding it
can use it before expiry, so avoid caching, emailing, indexing or persisting it.
Document visibility and tenant sharing need separate authorization enforcement
and explicit consent; a `source_url` pointing to a public third-party
document is not a private copy.

### Safe cutover

1. Inventory existing PM files and confirm where each file currently lives.
2. Back up all files and metadata with verifiable hashes and test restoring a sample.
3. Create a private R2 bucket and upload existing files preserving the exact storage keys.
4. Configure R2 secrets in staging, turn on `PM_R2_STORAGE_ENABLED` and verify old
   and new document keys both open after user authorization.
5. Verify wrong-account access is blocked, revoked access cannot issue new links,
   signed URLs expire, and download events can be audited.
6. Exercise upload, preview, attachment to an onboarding checklist, extraction,
   CSV export and final cleanup with a synthetic property.
7. Verify backups, versioning, lifecycle/retention policy, usage alerting,
   and a restore drill into a disposable bucket.
8. Repeat validation in production before enabling the flag there.

**Do not enable this flag before old files have been migrated**. Django
storage keys are preserved in PostgreSQL, and enabling R2 without copying
legacy objects means previously uploaded documents will no longer be found.
This PR does not migrate files or provision a bucket.

### Operational safeguards still required before broad rollout

- Upload MIME and extension allowlist, size caps, per-workspace quota,
  malware scanning and quarantine/pending status before exposing a new file.
- Content-disposition attachment for sensitive/non-previewable types.
- Version history/soft deletion/legal hold appropriate to lease record retention.
- Tenant/owner scoped access to files distinct from PM/staff permissions.
- Signed URL generation via a dedicated audited download endpoint where
  logging/authorization must be rechecked; never send R2 credentials to a browser.
- Direct-to-R2 presigned multipart uploads for large videos/scans after the
  small-file PM pilot has proved safe.
- Private encrypted backups and a routine restore test.

## Financial activation gate

A completed onboarding file checklist does **not** activate billing.
For a Section 8 account, verify the signed lease plus the housing
administrator's written current determination and effective date for each
payer split. Never use an abated MHA amount as tenant debt or assume it was paid.

Before enabling a daily billing cron: verify production database mapping for
every service, dry run against synthetic data, record a recovery point, confirm
idempotent replay and approval checkpoints, and test failed/refunded payments.

## Acceptance status (2026-11-03)

- Existing PM document API: present, uses local `MEDIA_ROOT` by default.
- Optional private R2 adapter and synthetic journey tests: implemented in
  branch, not enabled; subject to CI.
- R2 bucket/credentials, old-file migration, live download test, restore test:
  **not yet verified**.
- Roxana November billing: no posted charge; current lease shows total $1,485,
  tenant $1,108, MHA $377 but November MHA requires written verification.
- Tenant account invitation: pending; do not replace the resident email
  with the owner's login during tests.
