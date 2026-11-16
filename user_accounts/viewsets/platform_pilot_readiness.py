"""Founder-only pilot release signoff. Evidence is manual, never inferred from a UI deployment.

The existing ProductionReadinessState table is reused under a separate record key;
no tenant data, secrets, or payment information is copied into this checklist.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.production_readiness import ProductionReadinessState
from user_accounts.permissions import IsGodMode

RECORD_KEY = "PILOT_READINESS"
STATES = frozenset(("NOT_TESTED", "PASS", "FAIL", "BLOCKED"))

# All mandatory gates must have a separately reviewed passing attestation.
GATES = (
    ("personal_signup", "Identity", "Verified Personal signup",
     "Register with a fresh test email, confirm the six-digit code, log in, and reload the session."),
    ("existing_user_link", "Identity", "Existing-user role linking",
     "A signed-in account adds a workspace without creating a duplicate Personal identity."),
    ("password_recovery", "Identity", "Password recovery",
     "Request a reset, verify the message, set a new password, and sign in again."),
    ("role_permissions", "Identity", "Workspace entitlements and ModeBar",
     "An account only sees and enters authorized roles, including after a direct URL attempt."),
    ("pm_company", "Property Management", "PM company separation",
     "A management company creates and revisits its own PM workspace without a duplicate Service Business."),
    ("tenant_invite", "Property Management", "Tenant invitation and linking",
     "PM sends code and email; link prefills it and accepted access resolves to the correct company and unit."),
    ("owner_invite", "Property Management", "Property Owner / Partner invitation",
     "PM sends code and email; accepted access exposes only the owner’s approved properties."),
    ("invite_rejections", "Property Management", "Invitation safety",
     "Wrong email, expired/revoked/reused codes fail; a different PM company's records stay private."),
    ("mobile_shell", "Experience", "Mobile and desktop shell",
     "Review Personal, Business, PM, Tenant and Owner layouts and safe-area header navigation."),
    ("service_lifecycle", "Business", "Real service-request lifecycle",
     "Customer request -> ticket -> accept -> schedule -> complete -> invoice; statuses persist on reload."),
    ("business_pilot", "Business", "First business tester sign-off",
     "Use the founder Business Testers tracker with linked business, recorded checks and owner feedback."),
    ("billing_disclosure", "Payments", "Pricing, SWFF26 and fee disclosure",
     "Verify subscription waiver, 1% application fee presentation, $50 cap and cash collection rules."),
    ("stripe_sandbox", "Payments", "Controlled Stripe sandbox transaction",
     "Verify customer charge, fee allocation, failures, refund and disputes in test mode only."),
    ("bank_reconciliation", "Payments", "Receiving account and ledger reconciliation",
     "Verify transfer, deposit, receipt and reconciliation in the receiving legal entity's sandbox."),
    ("sandbox_accounts", "Test Lab", "Isolated role-based test accounts",
     "Use synthetic Personal, Business, Employee, PM, Tenant, and Owner accounts in staging; verify they have no production data or God Mode access."),
    ("test_entitlements", "Test Lab", "No-charge test entitlements",
     "Test every subscription and add-on without live charges. Verify server-side grants are staging-scoped, audited, and expire or revoke cleanly."),
    ("cross_device_sessions", "Test Lab", "Cross-device and session behavior",
     "Sign in on desktop and mobile simultaneously, then verify refresh, log out, expired sessions, and account-switch boundaries."),
    ("email_delivery_loop", "Communications", "Controlled two-way email test",
     "Send invitations and approved test messages only to controlled mailboxes; verify delivery, reply capture, opt-out, and message isolation."),
    ("notification_delivery_loop", "Communications", "Device notification round trip",
     "Test device enrollment, delivery, duplicate prevention, quiet hours, and revocation across iOS/web devices."),
    ("ai_execution_receipts", "AI Workforce", "Durable worker end-to-end evidence",
     "Confirm scheduled worker processes a synthetic task unattended, generates a receipt, awaits owner approval and resumes safely after authorization."),
    ("ai_worker_fail_safe", "AI Workforce", "Autonomous worker fail-safe",
     "Test duplicate claims, retries, lease expiry, cancellation, provider outage, budgets, and no unapproved external actions."),
    ("tenant_security", "Security", "Tenant-to-tenant isolation",
     "Verify direct API requests cannot expose other businesses, employees, tenant ledgers, documents, invoices, or AI memory."),
    ("admin_security", "Security", "God Mode and tester privilege boundaries",
     "Confirm tester accounts cannot access platform administration, impersonate owners, activate God Mode, or modify live entitlements."),
    ("api_security", "Security", "Application and integration security",
     "Validate MFA for admins, rate limiting, CSRF/session protections, secret redaction, webhook signatures, token rotation and dependency checks."),
    ("restore_failure_drill", "Security", "Backup and incident recovery drill",
     "Prove a staging restore, audit history retention, ability to disable workers, rollback strategy and incident response contact."),
    ("rollback", "Release", "Recovery and rollback",
     "Confirm error reporting, recovery steps, rollback target and support escalation."),
)
GATE_BY_ID = {item[0]: item for item in GATES}
MAX_NOTE_LENGTH = 1200
MAX_HISTORY = 150

# Specifications, not real accounts. No mailbox, token, password or customer data
# is ever created or returned by this readiness API.
TEST_PERSONAS = (
    ("personal_basic", "Personal", "Personal free tier; request creator; receives notifications"),
    ("personal_premium", "Personal + Assist", "Trial and purchased-add-on coverage with no real money"),
    ("business_owner", "Business owner", "CRM, leads, employees, scheduling, invoices and marketplace"),
    ("business_employee", "Employee", "Least-privilege assignment, schedule, and ticket access"),
    ("property_manager", "Property manager", "PM portfolio, leases, rent and Section 8 test fixtures"),
    ("tenant", "Tenant", "Maintenance requests, messages, and scoped rent ledger"),
    ("property_owner", "Property owner", "Owner-only property access and reporting"),
    ("sales_operator", "Sales OS", "Prospect pipeline and authorized outreach draft review"),
    ("growth_operator", "Growth OS", "Marketing drafts and publishing permission boundaries"),
    ("ai_workforce_owner", "Sync Assist", "Private pilot executor, approvals, costs, and receipts"),
)



def _serialize(record):
    raw = (record.certification or {}).get("gates", {}) if record else {}
    gates = []
    for key, group, title, instructions in GATES:
        item = raw.get(key, {}) if isinstance(raw, dict) else {}
        result = item.get("status") if item.get("status") in STATES else "NOT_TESTED"
        gates.append({
            "id": key, "group": group, "title": title, "instructions": instructions,
            "status": result, "evidence": item.get("evidence", "") if result != "NOT_TESTED" else "",
            "reviewed_at": item.get("reviewed_at"), "reviewed_by": item.get("reviewed_by"),
        })
    total = len(gates)
    passed = sum(gate["status"] == "PASS" for gate in gates)
    failed = sum(gate["status"] == "FAIL" for gate in gates)
    blocked = sum(gate["status"] == "BLOCKED" for gate in gates)
    return {
        "launch_ready": passed == total,
        "summary": {"passed": passed, "failed": failed, "blocked": blocked,
                    "not_tested": total-passed-failed-blocked, "total": total},
        "gates": gates,
        "recent_history": ((record.certification or {}).get("history") or [])[-15:][::-1] if record else [],
        "updated_at": record.updated_at.isoformat() if record else None,
        "notice": ("These are founder-recorded test attestations, not automated production checks. "
                   "A code merge, CI pass, or deployment cannot mark a manual gate as passed."),
    }


class PilotReadinessAPIView(APIView):
    permission_classes = (IsAuthenticated, IsGodMode)

    def get(self, request):
        state = ProductionReadinessState.objects.filter(key=RECORD_KEY).first()
        payload = _serialize(state)
        payload["test_lab"] = {
            "personas": [{"id": key, "role": role, "scenario": scenario}
                         for key, role, scenario in TEST_PERSONAS],
            "accounts_provisioned": False,
            "test_email_delivery_enabled": False,
            "environment_requirement": "Dedicated staging and synthetic test data only.",
            "notice": "This is a role-based test specification, not proof that accounts or devices are connected.",
        }
        return Response(payload)

    def patch(self, request):
        gate_id = str(request.data.get("gate_id") or "").strip()
        result = str(request.data.get("status") or "").strip().upper()
        evidence = request.data.get("evidence", "")
        if gate_id not in GATE_BY_ID:
            return Response({"detail": "Unknown pilot gate."}, status=400)
        if result not in STATES:
            return Response({"detail": "Status must be NOT_TESTED, PASS, FAIL, or BLOCKED."}, status=400)
        if not isinstance(evidence, str) or len(evidence) > MAX_NOTE_LENGTH:
            return Response({"detail": "Evidence must be short text (up to 1,200 characters)."}, status=400)
        evidence = evidence.strip()
        if result != "NOT_TESTED" and len(evidence) < 12:
            return Response({"detail": "Record at least 12 characters of concrete test evidence or a blocker."}, status=400)
        if result == "NOT_TESTED":
            evidence = ""
        with transaction.atomic():
            record, _ = ProductionReadinessState.objects.get_or_create(key=RECORD_KEY)
            record = ProductionReadinessState.objects.select_for_update().get(pk=record.pk)
            saved = dict(record.certification or {})
            gates = dict(saved.get("gates") or {})
            old = gates.get(gate_id) or {}
            now = timezone.now().isoformat()
            reviewer = str(getattr(request.user, "email", "") or request.user.pk)
            gates[gate_id] = {
                "status": result, "evidence": evidence, "reviewed_at": now,
                "reviewed_by": reviewer,
            }
            history = list(saved.get("history") or [])
            history.append({
                "gate_id": gate_id, "old_status": old.get("status", "NOT_TESTED"),
                "status": result, "at": now, "by": reviewer,
            })
            record.certification = {**saved, "gates": gates, "history": history[-MAX_HISTORY:]}
            record.updated_by = request.user
            record.save(update_fields=("certification", "updated_by", "updated_at"))
        return Response(_serialize(record))
