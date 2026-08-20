# SyncWorks Production Data Storage & Backup Plan

## Source of truth

Production application data must use PostgreSQL (`DB_ENGINE=postgres`). SQLite is for local development only. The application already reads PostgreSQL connection values from environment variables.

## Scale model

Operational records should remain normalized around durable IDs: users, businesses, BusinessMember/workforce profiles, tickets, ticket operations/SLA records, resources, assignments, billing records, affiliate attributions and commission ledger entries. High-volume event/history tables should be indexed by business/date/status and archived rather than deleted when possible.

Do not store clinical medical records in SyncWorks professional scheduling. Store only operational scheduling/communication data required for the workflow.

## Required production backup controls before broad customer onboarding

1. Managed PostgreSQL automated backups enabled at the hosting/database provider.
2. Point-in-time recovery (PITR) enabled when the production database plan supports it.
3. At least one daily backup retained outside the running application instance.
4. Minimum retention target: 7 daily + 4 weekly + 3 monthly recovery points until a formal retention policy replaces this baseline.
5. Quarterly restore drill into a non-production database. A backup that has never been restored is not considered verified.
6. Database credentials and backup destinations must stay in provider secrets/environment settings, never in GitHub.
7. Uploaded files/media should use durable object storage with versioning/backups; do not rely on an ephemeral web-service filesystem for irreplaceable customer files.

## Affiliate/revenue integrity

Affiliate attribution and commission ledger rows are financial audit records. Do not hard-delete them during normal operations. Refunds/reversals should create a VOID/CLAWED_BACK or compensating record so original lineage remains auditable.

Each commission-generating revenue event should include an idempotent `source_reference` so retries cannot double-pay an affiliate.

## Capacity monitoring

Before production volume materially increases, add alerts for:

- PostgreSQL storage utilization > 70% and > 85%
- backup failures
- connection saturation
- long-running queries
- table/index growth on tickets, messages, notifications, audit/event tables and affiliate ledger
- media/object-storage growth

## Restore priority

Tier 1: users/auth, businesses/team permissions, tickets/work, invoices/payments, affiliate attribution/ledger.

Tier 2: schedules, resources, notifications/messages, Personal settings/connections.

Tier 3: derived analytics, recommendations, cached discovery results and rebuildable summaries.

## Current limitation

This repository defines the application schema and backup requirements; provider-level automated snapshot/PITR settings must be verified in the production database host separately. Do not claim backups are active solely because this document exists.
