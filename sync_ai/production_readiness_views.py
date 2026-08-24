from __future__ import annotations

import os
from collections import Counter

from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, Invoice, InvoiceEvent, Notification, Ticket
from user_accounts.permissions import IsGodMode


def _present(*names: str) -> bool:
    return any(bool(str(os.getenv(name) or "").strip()) for name in names)


def _check(key: str, label: str, status: str, detail: str, *, category: str, action: str = "") -> dict:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "category": category,
        "action": action,
    }


def _database_check() -> tuple[dict, bool]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return _check("database_connectivity", "Database connectivity", "GREEN", "The application can query the configured database.", category="Data"), True
    except Exception:
        return _check("database_connectivity", "Database connectivity", "RED", "The application could not complete a database health query.", category="Data", action="Inspect the production database connection immediately."), False


def _latest_reminder_at():
    event = InvoiceEvent.objects.filter(event_type=InvoiceEvent.EventType.REMINDER).order_by("-occurred_at").first()
    return event.occurred_at.isoformat() if event else None


def build_production_readiness_payload() -> dict:
    checks: list[dict] = []
    db_check, db_ok = _database_check()
    checks.append(db_check)

    engine = str(settings.DATABASES.get("default", {}).get("ENGINE") or "")
    postgres = "postgresql" in engine
    checks.append(_check(
        "production_database",
        "Production database engine",
        "GREEN" if postgres else "YELLOW",
        "PostgreSQL is configured." if postgres else "This environment is not using PostgreSQL. SQLite is acceptable for local/test only.",
        category="Data",
        action="Verify DB_ENGINE=postgres in production." if not postgres else "",
    ))

    checks.append(_check(
        "debug_disabled",
        "Django debug disabled",
        "GREEN" if not settings.DEBUG else "RED",
        "DEBUG is disabled." if not settings.DEBUG else "DEBUG is enabled in this environment.",
        category="Security",
        action="Set DJANGO_DEBUG=false before public production use." if settings.DEBUG else "",
    ))

    secure_secret = str(getattr(settings, "SECRET_KEY", "")) not in {"", "dev-insecure-secret-change-me"}
    checks.append(_check(
        "secret_key",
        "Production secret key",
        "GREEN" if secure_secret else "RED",
        "A non-development Django secret is configured." if secure_secret else "The development/default Django secret is active.",
        category="Security",
        action="Set DJANGO_SECRET_KEY to a strong provider secret." if not secure_secret else "",
    ))

    secure_transport = bool(getattr(settings, "SESSION_COOKIE_SECURE", False) and getattr(settings, "CSRF_COOKIE_SECURE", False))
    checks.append(_check(
        "secure_cookies",
        "Secure auth cookies",
        "GREEN" if secure_transport else "YELLOW",
        "Session and CSRF secure-cookie flags are enabled." if secure_transport else "One or more secure-cookie flags are disabled in this environment.",
        category="Security",
    ))

    hsts = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
    checks.append(_check(
        "hsts",
        "HTTPS / HSTS policy",
        "GREEN" if hsts > 0 else "YELLOW",
        f"HSTS is enabled for {hsts} seconds." if hsts > 0 else "HSTS is not enabled in this environment.",
        category="Security",
    ))

    allowed_hosts = {str(value).lower() for value in getattr(settings, "ALLOWED_HOSTS", [])}
    host_ready = "syncworks-api.onrender.com" in allowed_hosts or "api.syncworksapp.com" in allowed_hosts
    checks.append(_check(
        "allowed_hosts",
        "Production API hosts",
        "GREEN" if host_ready else "RED",
        "A SyncWorks production API hostname is allowlisted." if host_ready else "Expected production API hosts are missing from ALLOWED_HOSTS.",
        category="Security",
    ))

    email_backend = str(getattr(settings, "EMAIL_BACKEND", ""))
    email_ready = bool("console" not in email_backend.lower() and getattr(settings, "EMAIL_HOST", "") and getattr(settings, "DEFAULT_FROM_EMAIL", ""))
    checks.append(_check(
        "email_delivery",
        "No-reply email delivery",
        "GREEN" if email_ready else "RED",
        "A non-console email backend, host, and sender are configured." if email_ready else "Email is not fully configured for real production delivery.",
        category="Communications",
        action="Verify EMAIL_BACKEND, EMAIL_HOST, credentials, and DEFAULT_FROM_EMAIL." if not email_ready else "",
    ))

    stripe_secret = bool(str(getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())
    stripe_webhook = bool(str(getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip())
    invoice_webhook = bool(str(getattr(settings, "STRIPE_INVOICE_WEBHOOK_SECRET", "") or "").strip())
    checks.append(_check(
        "stripe_core",
        "Stripe payment configuration",
        "GREEN" if stripe_secret and stripe_webhook else "RED",
        "Stripe secret key and primary webhook secret are configured." if stripe_secret and stripe_webhook else "Stripe payment credentials or the primary webhook secret are missing.",
        category="Payments",
    ))
    checks.append(_check(
        "stripe_invoice_webhook",
        "Invoice webhook separation",
        "GREEN" if invoice_webhook else "YELLOW",
        "A dedicated invoice webhook secret is configured." if invoice_webhook else "Invoice webhook uses fallback/shared configuration. Dedicated separation is preferred for production hardening.",
        category="Payments",
    ))

    openai_ready = _present("OPENAI_API_KEY")
    checks.append(_check("sync_ai_provider", "SYNC AI provider", "GREEN" if openai_ready else "YELLOW", "OPENAI_API_KEY is present." if openai_ready else "No OPENAI_API_KEY is visible to this runtime.", category="AI"))

    maps_ready = _present("GOOGLE_MAPS_SERVER_KEY", "GOOGLE_MAPS_API_KEY")
    checks.append(_check("maps_provider", "Maps / routing provider", "GREEN" if maps_ready else "YELLOW", "A Google Maps server key is present." if maps_ready else "Maps/routing will use reduced or fallback behavior without a configured server key.", category="Integrations"))

    meta_ready = bool(getattr(settings, "META_APP_ID", "") and getattr(settings, "META_APP_SECRET", ""))
    checks.append(_check("meta_growth", "Meta Growth connection", "GREEN" if meta_ready else "YELLOW", "Meta app credentials are configured." if meta_ready else "Meta social automation is not fully configured in this environment.", category="Integrations"))

    push_ready = bool(getattr(settings, "SYNC_PUSH_PROVIDER_CONFIGURED", False))
    checks.append(_check("push_provider", "Native/web push provider", "GREEN" if push_ready else "YELLOW", "Push provider is marked configured." if push_ready else "Push registration is prepared, but a delivery provider is not marked configured.", category="Communications"))

    media_root = str(getattr(settings, "MEDIA_ROOT", "") or "")
    checks.append(_check(
        "durable_media",
        "Durable uploaded-file storage",
        "YELLOW",
        f"Application media currently resolves through MEDIA_ROOT ({media_root or 'not set'}). Provider-level durable object storage/versioning cannot be proven from Django runtime.",
        category="Data",
        action="Verify durable object storage/versioning before broad onboarding.",
    ))

    checks.append(_check(
        "backups_pitr",
        "Automated backups + PITR",
        "YELLOW",
        "Provider-level PostgreSQL backups, retention, PITR, and restore testing cannot be verified from application code.",
        category="Recovery",
        action="Verify automated backups/PITR at the database provider and record a restore drill.",
    ))

    checks.append(_check(
        "stripe_event_ledger",
        "Global Stripe event idempotency ledger",
        "YELLOW",
        "Invoice reminder events are idempotent, but the existing Stripe production audit still recommends a persistent global Stripe webhook event ledger.",
        category="Payments",
        action="Add a durable Stripe event-id ledger before high-volume unrestricted launch.",
    ))

    counts = Counter(row["status"] for row in checks)
    weighted = counts["GREEN"] + (counts["YELLOW"] * 0.5)
    readiness_percent = round((weighted / len(checks)) * 100) if checks else 0
    launch_blockers = [row for row in checks if row["status"] == "RED"]

    metrics = {}
    if db_ok:
        try:
            metrics = {
                "businesses": Business.objects.count(),
                "tickets": Ticket.objects.count(),
                "invoices": Invoice.objects.count(),
                "notifications": Notification.objects.count(),
                "applied_migrations": MigrationRecorder.Migration.objects.count(),
                "last_invoice_reminder_at": _latest_reminder_at(),
            }
        except Exception:
            metrics = {"metrics_error": True}

    return {
        "generated_at": timezone.now().isoformat(),
        "environment": {
            "debug": bool(settings.DEBUG),
            "database_vendor": connection.vendor,
            "frontend_url": str(getattr(settings, "FRONTEND_URL", "") or ""),
            "email_sender": str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""),
        },
        "summary": {
            "readiness_percent": readiness_percent,
            "green": counts["GREEN"],
            "yellow": counts["YELLOW"],
            "red": counts["RED"],
            "launch_blocker_count": len(launch_blockers),
            "application_gate": "BLOCKED" if launch_blockers else "PASS_WITH_EXTERNAL_VERIFICATION",
        },
        "checks": checks,
        "launch_blockers": launch_blockers,
        "metrics": metrics,
        "external_verification_required": [
            "Database automated backup policy and PITR",
            "Successful restore drill",
            "Durable media/object storage and versioning",
            "Production Stripe webhook endpoint/secrets in provider dashboard",
            "Frontend/backend deployment status",
            "Real-device mobile smoke test",
        ],
    }


class ProductionReadinessAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        return Response(build_production_readiness_payload())
