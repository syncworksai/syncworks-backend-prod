#!/usr/bin/env bash
# Render Cron entrypoint for the private Sync Assist pilot.
# Default OFF. Never executes work until both worker gates are explicitly enabled.
set -euo pipefail

if [[ "${SYNC_ASSIST_DURABLE_WORKER_ENABLED:-false}" != "true" || "${SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED:-false}" != "true" ]]; then
  echo "SYNC Assist scheduled execution disabled (no jobs executed)."
  exit 0
fi

# Fail closed: do not let a standalone Render cron silently fall back to SQLite.
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is missing. Connect the Ohio production database privately in Render." >&2
  exit 2
fi

# Verify the database protocol without printing credentials or the connection URL.
python - <<'PY'
import os
from urllib.parse import urlsplit
parsed = urlsplit(os.environ["DATABASE_URL"])
if parsed.scheme not in ("postgres", "postgresql", "postgresql+psycopg2") or not parsed.hostname:
    raise SystemExit("ERROR: Scheduled runner requires a valid PostgreSQL DATABASE_URL.")
print("SYNC Assist database configuration: PostgreSQL URL present (credentials hidden).")
PY

# Bound each cron invocation to ONE authorized, internal-only step.
# --scheduled emits a worker-tick receipt for audit and monitoring.
exec python manage.py sync_assist_queue_worker --once --scheduled --max-jobs 1
