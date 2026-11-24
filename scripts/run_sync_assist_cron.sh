#!/usr/bin/env bash
# Render cron: fail closed unless approved for the restricted private pilot.
set -euo pipefail

# Each worker is independently gated. Do not require the unrelated SYNC Assist
# worker to be active for one tightly scoped synthetic freelance test.
sync_assist_run=false
if [[ "${SYNC_ASSIST_DURABLE_WORKER_ENABLED:-false}" == "true" && "${SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED:-false}" == "true" ]]; then
  sync_assist_run=true
fi
freelance_test_run=false
if [[ "${FREELANCE_SYNTHETIC_WORKER_ENABLED:-false}" == "true" && -n "${FREELANCE_SYNTHETIC_PILOT_JOB_ID:-}" ]]; then
  freelance_test_run=true
fi
if [[ "${SYNC_ASSIST_PREFLIGHT_ONLY:-false}" != "true" && "$sync_assist_run" != "true" && "$freelance_test_run" != "true" ]]; then
  echo "All scheduled workers disabled (no jobs executed)."
  exit 0
fi

# Verify Django's EFFECTIVE connection. The application does not configure
# DATABASES from DATABASE_URL; checking that variable alone is insufficient.
# The Ohio pilot job table is in syncworks_db, not the Oregon empty database.
python - <<'PY' || exit 2
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "syncworksv7.settings")
from django.conf import settings

cfg = settings.DATABASES["default"]
if cfg.get("ENGINE") != "django.db.backends.postgresql":
    sys.exit("ERROR: Scheduled worker requires Django PostgreSQL configuration (DB_ENGINE=postgres).")
if str(cfg.get("NAME", "")) != "syncworks_db":
    sys.exit("ERROR: Scheduled worker must use the designated Ohio pilot database.")
if not cfg.get("HOST") or not cfg.get("USER") or not cfg.get("PASSWORD"):
    sys.exit("ERROR: Scheduled worker PostgreSQL connection is incomplete.")

import django
django.setup()
from django.db import connection
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        observed = cursor.fetchone()[0]
        if observed != "syncworks_db":
            sys.exit("ERROR: Scheduled worker connected to an unexpected database.")
        cursor.execute("SELECT 1 FROM user_accounts_syncassistjob LIMIT 0")
        cursor.execute("SELECT 1 FROM user_accounts_auditlog LIMIT 0")
except Exception as exc:
    # Do not log connection secrets or a raw psycopg error.
    sys.exit("ERROR: Scheduled worker database or schema is unavailable.")
print("SYNC Assist preflight passed: Django PostgreSQL and required job tables verified.")
PY

if [[ "${SYNC_ASSIST_PREFLIGHT_ONLY:-false}" == "true" ]]; then
  echo "SYNC Assist preflight-only check completed (no jobs executed)."
  exit 0
fi

# Optional hourly Sarah mailbox scan; requires explicit opt-in and OAuth credentials
# on this SAME cron service. The command checks the last scan time per mailbox.
if [[ "${SYNC_ASSIST_SARAH_SCAN_ENABLED:-false}" == "true" ]]; then
  python manage.py sarah_property_mail_scan || echo "Sarah mailbox review skipped after an error."
fi

# Optional bounded freelance synthetic test. Target UUID is mandatory and claim
# scope cannot fall back to another queued job. Zero model/provider calls.
# Keep this separate from the primary Sync Assist task execution.
if [[ "$freelance_test_run" == "true" ]]; then
  python manage.py freelance_synthetic_worker --once --max-jobs 1 --job-id "$FREELANCE_SYNTHETIC_PILOT_JOB_ID"
fi

# Run the separate SYNC Assist worker only if its own gates are enabled.
if [[ "$sync_assist_run" == "true" ]]; then
  exec python manage.py sync_assist_queue_worker --once --scheduled --max-jobs 1
fi
echo "Bounded freelance-only run complete (SYNC Assist scheduled execution remains disabled)."
