from __future__ import annotations

import json
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.urls import NoReverseMatch, reverse
from rest_framework.test import APIClient


@dataclass
class RouteCheck:
    label: str
    name: str
    kwargs: dict | None = None


@dataclass
class EndpointCheck:
    label: str
    path: str
    needs_business_header: bool = False


ROUTE_CHECKS = [
    RouteCheck("Business list", "businesses-list"),
    RouteCheck("My businesses", "me-businesses-list"),
    RouteCheck("Business customers", "business-customers-list"),
    RouteCheck("Business KPIs", "business-kpis-summary"),
    RouteCheck("Business projects", "business-projects-list"),
    RouteCheck("Service categories", "service-categories-list"),
    RouteCheck("Service requests", "service-requests-list"),
    RouteCheck("Service catalog", "service-catalog-list"),
    RouteCheck("Tickets", "tickets-list"),
    RouteCheck("Ticket messages", "ticket-messages-list"),
    RouteCheck("Ticket attachments", "ticket-attachments-list"),
    RouteCheck("Ticket quotes", "ticket-quotes-list"),
    RouteCheck("Invoices", "invoices-list"),
    RouteCheck("Cash fee invoices", "cash-fee-invoices-list"),
    RouteCheck("Partner work tickets", "partner-work-tickets-list"),
    RouteCheck("Partner estimates", "partner-work-estimates-list"),
    RouteCheck("Partner change orders", "partner-change-orders-list"),
    RouteCheck("Partner invoices", "partner-invoices-list"),
    RouteCheck("Partner payments", "partner-payments-list"),
    RouteCheck("Workflow priority queue", "workflow-priority-queue"),
    RouteCheck("Ticket zip metrics", "tickets-metrics-zip"),
    RouteCheck("Ticket conversations", "ticket-conversation-list"),
    RouteCheck("Billing status", "billing-status"),
    RouteCheck("Subscription status", "sub-status"),
]

SAFE_ENDPOINT_CHECKS = [
    EndpointCheck("Auth me", "/api/v1/auth/me/"),
    EndpointCheck("Me alias", "/api/v1/me/"),
    EndpointCheck("My businesses", "/api/v1/me/businesses/"),
    EndpointCheck("Business list", "/api/v1/businesses/"),
    EndpointCheck("Service categories", "/api/v1/service-categories/"),
    EndpointCheck("Service requests", "/api/v1/service-requests/"),
    EndpointCheck("Service catalog", "/api/v1/service-catalog/"),
    EndpointCheck("Tickets", "/api/v1/tickets/"),
    EndpointCheck("Ticket quotes", "/api/v1/ticket-quotes/"),
    EndpointCheck("Invoices", "/api/v1/invoices/"),
    EndpointCheck("Cash fee invoices", "/api/v1/cash-fee-invoices/"),
    EndpointCheck("Ticket conversations", "/api/v1/ticket-conversations/"),
    EndpointCheck("Billing status", "/api/v1/billing/status/", True),
    EndpointCheck("Subscription status", "/api/v1/billing/subscription/status/", True),
]


class Command(BaseCommand):
    help = (
        "Run a safe SyncWorks Business/Ticket production smoke check. "
        "By default it verifies URL registration only. "
        "Pass --user-email for safe authenticated GET/list endpoint checks."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-email",
            default="",
            help="Optional user email for authenticated endpoint smoke checks.",
        )
        parser.add_argument(
            "--business-id",
            default="",
            help="Optional business id to send as X-Business-Id for business-context endpoints.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output JSON summary.",
        )

    def handle(self, *args, **options):
        route_results = self._check_routes()
        endpoint_results = []

        user_email = str(options.get("user_email") or "").strip()
        business_id = str(options.get("business_id") or "").strip()

        if user_email:
            endpoint_results = self._check_endpoints(
                user_email=user_email,
                business_id=business_id,
            )

        summary = {
            "routes_checked": len(route_results),
            "routes_ok": sum(1 for item in route_results if item["ok"]),
            "routes_failed": [item for item in route_results if not item["ok"]],
            "endpoints_checked": len(endpoint_results),
            "endpoints_ok": sum(1 for item in endpoint_results if item["ok"]),
            "endpoints_warn": [item for item in endpoint_results if not item["ok"]],
        }

        if options.get("json"):
            self.stdout.write(json.dumps(summary, indent=2, default=str))
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Business/Ticket route smoke check"))
        self.stdout.write("-" * 48)

        for item in route_results:
            if item["ok"]:
                self.stdout.write(self.style.SUCCESS(f"OK route: {item['label']} -> {item['path']}"))
            else:
                self.stdout.write(self.style.ERROR(f"FAIL route: {item['label']} ({item['name']}) {item['error']}"))

        if user_email:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Authenticated endpoint smoke check"))
            self.stdout.write("-" * 48)

            for item in endpoint_results:
                status = item.get("status_code")
                if item["ok"]:
                    self.stdout.write(self.style.SUCCESS(f"OK endpoint: {item['label']} -> {status}"))
                else:
                    self.stdout.write(self.style.WARNING(f"WARN endpoint: {item['label']} -> {status} {item.get('detail', '')}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Routes OK: {summary['routes_ok']}/{summary['routes_checked']}"
            )
        )

        if user_email:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Endpoint OK: {summary['endpoints_ok']}/{summary['endpoints_checked']}"
                )
            )

        if summary["routes_failed"]:
            raise SystemExit(1)

    def _check_routes(self):
        results = []

        for check in ROUTE_CHECKS:
            try:
                path = reverse(check.name, kwargs=check.kwargs or None)
                results.append(
                    {
                        "label": check.label,
                        "name": check.name,
                        "ok": True,
                        "path": path,
                    }
                )
            except NoReverseMatch as exc:
                results.append(
                    {
                        "label": check.label,
                        "name": check.name,
                        "ok": False,
                        "error": str(exc),
                    }
                )

        return results

    def _check_endpoints(self, *, user_email: str, business_id: str):
        User = get_user_model()
        user = User.objects.filter(email__iexact=user_email).first()

        if not user:
            return [
                {
                    "label": "User lookup",
                    "path": "",
                    "ok": False,
                    "status_code": "USER_NOT_FOUND",
                    "detail": f"No user found for {user_email}",
                }
            ]

        client = APIClient()
        client.force_authenticate(user=user)

        results = []

        for check in SAFE_ENDPOINT_CHECKS:
            headers = {}

            if check.needs_business_header and business_id:
                headers["HTTP_X_BUSINESS_ID"] = business_id

            try:
                headers["HTTP_HOST"] = "localhost"
                response = client.get(check.path, **headers)
                status_code = response.status_code

                ok = status_code in {
                    200,
                    204,
                    400,
                    402,
                    403,
                    404,
                }

                # 401 means auth failed, 500 means server error. Those are true smoke failures.
                if status_code in {401, 500}:
                    ok = False

                detail = ""
                if not ok:
                    try:
                        detail = str(response.data)[:500]
                    except Exception:
                        detail = str(getattr(response, "content", b""))[:500]

                results.append(
                    {
                        "label": check.label,
                        "path": check.path,
                        "ok": ok,
                        "status_code": status_code,
                        "detail": detail,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "label": check.label,
                        "path": check.path,
                        "ok": False,
                        "status_code": "EXCEPTION",
                        "detail": str(exc),
                    }
                )

        return results