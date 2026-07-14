from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

try:
    from rest_framework.test import APIClient
except Exception:  # pragma: no cover
    APIClient = None


@dataclass
class CheckResult:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class RouteNameCheck:
    label: str
    name: str
    required: bool = True


@dataclass
class EndpointCheck:
    label: str
    path: str
    acceptable: set[int]
    needs_business_header: bool = False


CORE_ROUTE_NAMES = [
    RouteNameCheck("Billing status", "billing-status"),
    RouteNameCheck("Subscription status", "sub-status"),
    RouteNameCheck("Invoices", "invoices-list"),
    RouteNameCheck("Cash fee invoices", "cash-fee-invoices-list"),
    RouteNameCheck("Business list", "businesses-list"),
    RouteNameCheck("My businesses", "me-businesses-list"),
    RouteNameCheck("Growth drafts", "platform-growth-drafts-list", required=False),
    RouteNameCheck("Affiliate me", "affiliate-me", required=False),
]


PAYMENT_ENDPOINTS = [
    EndpointCheck("Billing status", "/api/v1/billing/status/", {200, 204, 400, 402, 403, 404}, True),
    EndpointCheck("Subscription status", "/api/v1/billing/subscription/status/", {200, 204, 400, 402, 403, 404}, True),
    EndpointCheck("Invoices", "/api/v1/invoices/", {200, 204, 400, 403, 404}),
    EndpointCheck("Cash fee invoices", "/api/v1/cash-fee-invoices/", {200, 204, 400, 403, 404}),
    EndpointCheck("Business list", "/api/v1/businesses/", {200, 204, 400, 403, 404}),
    EndpointCheck("My businesses", "/api/v1/me/businesses/", {200, 204, 400, 403, 404}),
]


class Command(BaseCommand):
    help = "Read-only payment, subscription, affiliate, and billing smoke check for SyncWorks."

    def add_arguments(self, parser):
        parser.add_argument("--user-email", default="", help="Authenticated user email for endpoint smoke checks.")
        parser.add_argument("--business-id", default="", help="Business ID to send as X-Business-ID.")
        parser.add_argument(
            "--strict-env",
            action="store_true",
            help="Fail if payment environment variables are missing. Default reports warnings only.",
        )
        parser.add_argument(
            "--skip-endpoints",
            action="store_true",
            help="Skip authenticated endpoint GET checks.",
        )
        parser.add_argument(
            "--json-summary",
            action="store_true",
            help="Print a compact JSON-like summary only at the end.",
        )

    def handle(self, *args, **options):
        self.failures: list[CheckResult] = []
        self.warnings: list[CheckResult] = []

        user_email = (options.get("user_email") or "").strip()
        business_id = str(options.get("business_id") or "").strip()
        strict_env = bool(options.get("strict_env"))
        skip_endpoints = bool(options.get("skip_endpoints"))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("SyncWorks Payment + Subscription Smoke Check"))
        self.stdout.write("-" * 64)

        self._section("Model and field checks")
        self._check_payment_models()

        self._section("Affiliate / Health revenue checks")
        self._check_affiliate_revenue_sources()

        self._section("Environment readiness")
        self._check_payment_environment(strict_env=strict_env)

        self._section("Migration drift checks")
        self._check_migration_drift()

        self._section("URL route checks")
        self._check_route_names()
        self._check_route_resolution()

        if not skip_endpoints:
            self._section("Authenticated payment endpoint checks")
            self._check_authenticated_endpoints(user_email=user_email, business_id=business_id)

        self._section("Summary")
        self._print_summary(strict_env=strict_env)

    def _section(self, title: str) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(title))
        self.stdout.write("-" * 64)

    def _ok(self, label: str, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        self.stdout.write(self.style.SUCCESS(f"OK {label}{suffix}"))

    def _warn(self, label: str, detail: str = "") -> None:
        self.warnings.append(CheckResult(label=label, ok=False, detail=detail))
        suffix = f" - {detail}" if detail else ""
        self.stdout.write(self.style.WARNING(f"WARN {label}{suffix}"))

    def _fail(self, label: str, detail: str = "") -> None:
        self.failures.append(CheckResult(label=label, ok=False, detail=detail))
        suffix = f" - {detail}" if detail else ""
        self.stdout.write(self.style.ERROR(f"FAIL {label}{suffix}"))

    def _get_model(self, app_label: str, model_name: str):
        try:
            return apps.get_model(app_label, model_name)
        except LookupError:
            self._fail(f"{app_label}.{model_name}", "model not registered")
            return None

    def _model_fields(self, model) -> set[str]:
        return {field.name for field in model._meta.fields}

    def _db_columns(self, model) -> set[str]:
        table = model._meta.db_table
        with connection.cursor() as cursor:
            try:
                description = connection.introspection.get_table_description(cursor, table)
            except Exception as exc:
                self._fail(f"{model.__name__} DB table", str(exc))
                return set()
        return {col.name for col in description}

    def _check_required_fields(self, model, required: list[str], label: str) -> None:
        model_fields = self._model_fields(model)
        db_columns = self._db_columns(model)
        missing_model = [field for field in required if field not in model_fields]
        missing_db = []

        for field in required:
            try:
                column = model._meta.get_field(field).column
            except Exception:
                column = field
            if column not in db_columns:
                missing_db.append(column)

        if missing_model:
            self._fail(label, f"missing model fields: {', '.join(missing_model)}")
        elif missing_db:
            self._fail(label, f"missing DB columns: {', '.join(missing_db)}")
        else:
            self._ok(label, f"{len(required)} required fields present in model and DB")

    def _check_payment_models(self) -> None:
        Invoice = self._get_model("user_accounts", "Invoice")
        CashFeeInvoice = self._get_model("user_accounts", "CashFeeInvoice")
        Business = self._get_model("user_accounts", "Business")

        try:
            UserBillingProfile = apps.get_model("user_accounts", "UserBillingProfile")
        except LookupError:
            UserBillingProfile = None

        if Invoice:
            self._check_required_fields(
                Invoice,
                [
                    "ticket",
                    "title",
                    "notes",
                    "subtotal",
                    "tax",
                    "total",
                    "status",
                    "due_date",
                    "payment_method",
                    "amount_paid",
                    "paid_at",
                    "platform_fee_rate_bps",
                    "platform_fee_amount",
                    "platform_fee_collected",
                    "platform_fee_collected_at",
                    "stripe_checkout_session_id",
                    "stripe_payment_intent_id",
                    "stripe_charge_id",
                    "stripe_transfer_id",
                    "created_at",
                    "updated_at",
                ],
                "Invoice billing fields",
            )

            status_choices = {choice[0] for choice in getattr(Invoice, "Status").choices} if hasattr(Invoice, "Status") else set()
            expected_statuses = {"DRAFT", "SENT", "PAID", "VOID"}
            if expected_statuses.issubset(status_choices):
                self._ok("Invoice statuses", ", ".join(sorted(status_choices)))
            else:
                self._fail("Invoice statuses", f"expected at least {sorted(expected_statuses)} got {sorted(status_choices)}")

            payment_choices = (
                {choice[0] for choice in getattr(Invoice, "PaymentMethod").choices}
                if hasattr(Invoice, "PaymentMethod")
                else set()
            )
            expected_methods = {"CARD", "CASH", "OTHER"}
            if expected_methods.issubset(payment_choices):
                self._ok("Invoice payment methods", ", ".join(sorted(payment_choices)))
            else:
                self._fail("Invoice payment methods", f"expected {sorted(expected_methods)} got {sorted(payment_choices)}")

            try:
                inv = Invoice(total=Decimal("100.00"))
                inv.recompute_platform_fee()
                fee = getattr(inv, "platform_fee_amount", None)
                if fee == Decimal("1.00"):
                    self._ok("Invoice platform fee math", "$100.00 at 1 percent = $1.00")
                else:
                    self._fail("Invoice platform fee math", f"expected 1.00 got {fee}")
            except Exception as exc:
                self._fail("Invoice platform fee math", str(exc))

        if CashFeeInvoice:
            self._check_required_fields(
                CashFeeInvoice,
                [
                    "business",
                    "amount_cents",
                    "status",
                    "period_start",
                    "period_end",
                    "due_date",
                    "memo",
                    "paid_at",
                    "created_by",
                    "created_at",
                    "updated_at",
                ],
                "CashFeeInvoice fee-tracking fields",
            )

        if Business:
            business_fields = self._model_fields(Business)
            expected_any = [
                "billing_exempt",
                "subscription_exempt",
                "subscription_status",
                "stripe_customer_id",
                "stripe_subscription_id",
            ]
            present = [field for field in expected_any if field in business_fields]
            if present:
                self._ok("Business billing/subscription markers", ", ".join(present))
            else:
                self._warn(
                    "Business billing/subscription markers",
                    "No obvious subscription marker fields found on Business; endpoint may compute status elsewhere.",
                )

        if UserBillingProfile:
            profile_fields = self._model_fields(UserBillingProfile)
            present = [
                field
                for field in ["stripe_customer_id", "beta_access_code", "health_access", "finance_access"]
                if field in profile_fields
            ]
            self._ok("UserBillingProfile registered", ", ".join(present) if present else "model exists")
        else:
            self._warn("UserBillingProfile", "model not registered; okay if billing is business-only")

    def _check_affiliate_revenue_sources(self) -> None:
        Ledger = self._get_model("platform_affiliates", "AffiliateCommissionLedger")
        if Ledger:
            try:
                field = Ledger._meta.get_field("revenue_source")
                choices = {choice[0] for choice in field.choices}
                expected = {
                    "PLATFORM_FEE",
                    "SBO_SUBSCRIPTION",
                    "GROWTH_OS_SUBSCRIPTION",
                    "HEALTH_SUBSCRIPTION",
                    "HEALTH_AI_SUBSCRIPTION",
                    "OTHER_SYNCWORKS_REVENUE",
                }
                missing = sorted(expected - choices)
                if missing:
                    self._fail("Affiliate revenue_source choices", f"missing: {', '.join(missing)}")
                else:
                    self._ok("Affiliate revenue_source choices", ", ".join(sorted(choices)))
            except Exception as exc:
                self._fail("Affiliate revenue_source choices", str(exc))

        try:
            from platform_affiliates.services.commission_service import record_user_health_subscription_commission  # noqa: F401

            self._ok("Health affiliate commission service import")
        except Exception as exc:
            self._fail("Health affiliate commission service import", str(exc))

        try:
            from platform_affiliates.management.commands.record_health_affiliate_commission import Command as _Command  # noqa: F401

            self._ok("Manual health affiliate commission command import")
        except Exception as exc:
            self._fail("Manual health affiliate commission command import", str(exc))

    def _check_payment_environment(self, *, strict_env: bool) -> None:
        env_groups = {
            "Stripe secret key": ["STRIPE_SECRET_KEY"],
            "Stripe publishable key": ["STRIPE_PUBLISHABLE_KEY", "VITE_STRIPE_PUBLISHABLE_KEY"],
            "Stripe webhook secret": ["STRIPE_WEBHOOK_SECRET"],
            "Frontend/base URL": ["FRONTEND_URL", "PUBLIC_FRONTEND_URL", "SITE_URL"],
            "Backend/API URL": ["BACKEND_URL", "API_BASE_URL", "RENDER_EXTERNAL_URL"],
        }

        for label, keys in env_groups.items():
            present_key = next((key for key in keys if os.environ.get(key)), "")
            if present_key:
                value = os.environ.get(present_key, "")
                safe_detail = f"{present_key} present"
                if present_key == "STRIPE_SECRET_KEY":
                    if value.startswith("sk_test_"):
                        safe_detail += " (test mode)"
                    elif value.startswith("sk_live_"):
                        safe_detail += " (live mode)"
                    else:
                        safe_detail += " (prefix not recognized)"
                self._ok(label, safe_detail)
            else:
                detail = "missing any of: " + ", ".join(keys)
                if strict_env:
                    self._fail(label, detail)
                else:
                    self._warn(label, detail)

    def _check_migration_drift(self) -> None:
        for app_label in ["user_accounts", "platform_affiliates", "platform_growth", "customer_health"]:
            try:
                call_command(
                    "makemigrations",
                    app_label,
                    check=True,
                    dry_run=True,
                    no_input=True,
                    verbosity=0,
                )
                self._ok(f"Migration drift: {app_label}", "no changes detected")
            except SystemExit as exc:
                if getattr(exc, "code", 1) == 0:
                    self._ok(f"Migration drift: {app_label}", "no changes detected")
                else:
                    self._fail(f"Migration drift: {app_label}", f"makemigrations exited {exc.code}")
            except Exception as exc:
                self._fail(f"Migration drift: {app_label}", str(exc))

    def _check_route_names(self) -> None:
        for check in CORE_ROUTE_NAMES:
            try:
                path = reverse(check.name)
                self._ok(f"Route name: {check.label}", f"{check.name} -> {path}")
            except NoReverseMatch as exc:
                if check.required:
                    self._fail(f"Route name: {check.label}", f"{check.name} not found: {exc}")
                else:
                    self._warn(f"Route name: {check.label}", f"{check.name} not found; may be optional or differently mounted")

    def _check_route_resolution(self) -> None:
        paths = [
            "/api/v1/billing/status/",
            "/api/v1/billing/subscription/status/",
            "/api/v1/invoices/",
            "/api/v1/cash-fee-invoices/",
            "/api/v1/businesses/",
            "/api/v1/me/businesses/",
            "/api/v1/platform-growth/growth/drafts/",
            "/api/v1/platform-affiliates/me/",
        ]

        for path in paths:
            try:
                match = resolve(path)
                view_name = getattr(match, "view_name", "") or str(match.func)
                self._ok(f"Route resolves: {path}", view_name)
            except Resolver404:
                if path in [
                    "/api/v1/billing/status/",
                    "/api/v1/billing/subscription/status/",
                    "/api/v1/invoices/",
                    "/api/v1/cash-fee-invoices/",
                ]:
                    self._fail(f"Route resolves: {path}", "not found")
                else:
                    self._warn(f"Route resolves: {path}", "not found; may be mounted under a different base")

    def _check_authenticated_endpoints(self, *, user_email: str, business_id: str) -> None:
        if not user_email:
            self._warn("Authenticated endpoint checks", "skipped because --user-email was not provided")
            return

        if APIClient is None:
            self._fail("Authenticated endpoint checks", "rest_framework.test.APIClient is unavailable")
            return

        User = get_user_model()
        user = User.objects.filter(email__iexact=user_email).first()
        if not user:
            self._fail("Authenticated user lookup", f"user not found: {user_email}")
            return

        client = APIClient()
        client.force_authenticate(user=user)

        for check in PAYMENT_ENDPOINTS:
            headers: dict[str, Any] = {"HTTP_HOST": "localhost"}
            if check.needs_business_header and business_id:
                headers["HTTP_X_BUSINESS_ID"] = business_id

            try:
                response = client.get(check.path, **headers)
                status_code = int(response.status_code)
                if status_code in check.acceptable and status_code not in {401, 500}:
                    self._ok(f"Endpoint: {check.label}", f"{status_code} {check.path}")
                else:
                    detail = ""
                    try:
                        detail = str(response.data)[:400]
                    except Exception:
                        try:
                            detail = response.content[:400].decode("utf-8", errors="replace")
                        except Exception:
                            detail = ""
                    self._fail(f"Endpoint: {check.label}", f"{status_code} {check.path} {detail}")
            except Exception as exc:
                self._fail(f"Endpoint: {check.label}", str(exc))

    def _print_summary(self, *, strict_env: bool) -> None:
        if self.warnings:
            self.stdout.write(self.style.WARNING(f"Warnings: {len(self.warnings)}"))
            for warning in self.warnings:
                self.stdout.write(self.style.WARNING(f"  - {warning.label}: {warning.detail}"))
        else:
            self.stdout.write(self.style.SUCCESS("Warnings: 0"))

        if self.failures:
            self.stdout.write(self.style.ERROR(f"Failures: {len(self.failures)}"))
            for failure in self.failures:
                self.stdout.write(self.style.ERROR(f"  - {failure.label}: {failure.detail}"))
            raise CommandError("Payment smoke check failed.")

        self.stdout.write(self.style.SUCCESS("Failures: 0"))
        self.stdout.write(self.style.SUCCESS("Payment smoke check passed."))
        if self.warnings and not strict_env:
            self.stdout.write(
                self.style.WARNING(
                    "Warnings are allowed in non-strict mode. Use --strict-env when validating production env readiness."
                )
            )