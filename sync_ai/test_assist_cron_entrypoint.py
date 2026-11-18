"""Fail-closed tests for the independent Render cron shell entrypoint."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from django.test import SimpleTestCase


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_sync_assist_cron.sh"


class ScheduledWorkerEntrypointTests(SimpleTestCase):
    def _invoke(self, **flags):
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            **flags,
        }
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=str(SCRIPT.parent.parent),
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_is_disabled_without_explicit_both_gates(self):
        for flags in (
            {},
            {"SYNC_ASSIST_DURABLE_WORKER_ENABLED": "true"},
            {"SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED": "true"},
        ):
            with self.subTest(flags=flags):
                result = self._invoke(**flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("disabled", result.stdout.lower())
                self.assertNotIn("Processed", result.stdout)

    def test_rejects_missing_postgres_connection_when_enabled(self):
        result = self._invoke(
            SYNC_ASSIST_DURABLE_WORKER_ENABLED="true",
            SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED="true",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Django PostgreSQL configuration", result.stderr)

    def test_rejects_non_postgresql_database_url(self):
        result = self._invoke(
            SYNC_ASSIST_DURABLE_WORKER_ENABLED="true",
            SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED="true",
            DATABASE_URL="sqlite:///tmp/test.sqlite3",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Django PostgreSQL configuration", result.stderr)
        self.assertNotIn("sqlite:///tmp/test.sqlite3", result.stderr)

    def test_rejects_wrong_postgres_database_before_connecting(self):
        result = self._invoke(
            SYNC_ASSIST_DURABLE_WORKER_ENABLED="true",
            SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED="true",
            DB_ENGINE="postgres",
            POSTGRES_DB="not_the_pilot_database",
            POSTGRES_HOST="localhost",
            POSTGRES_USER="dummy",
            POSTGRES_PASSWORD="dummy",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("designated Ohio pilot database", result.stderr)

    def test_database_url_alone_cannot_override_sqlite(self):
        result = self._invoke(
            SYNC_ASSIST_DURABLE_WORKER_ENABLED="true",
            SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED="true",
            DATABASE_URL="postgresql://unused.invalid/fake",
            DB_ENGINE="sqlite",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Django PostgreSQL configuration", result.stderr)
        self.assertNotIn("unused.invalid", result.stderr)

    def test_preflight_only_checks_database_without_worker_flags(self):
        result = self._invoke(
            SYNC_ASSIST_PREFLIGHT_ONLY="true",
            DB_ENGINE="postgres",
            POSTGRES_DB="unexpected_database",
            POSTGRES_HOST="localhost",
            POSTGRES_USER="dummy",
            POSTGRES_PASSWORD="dummy",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("designated Ohio pilot database", result.stderr)
        self.assertNotIn("Processed", result.stdout)
