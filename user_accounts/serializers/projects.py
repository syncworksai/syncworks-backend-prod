from __future__ import annotations

from decimal import Decimal
from rest_framework import serializers

from user_accounts.models import BusinessProject, Ticket

COMPLETED_STATUSES = {
    Ticket.Status.COMPLETED, Ticket.Status.INVOICED,
    Ticket.Status.PAID, Ticket.Status.CLOSED,
}


def _money(cents):
    return str((Decimal(int(cents or 0)) / Decimal("100")).quantize(Decimal("0.01")))


def project_rollup(project):
    children = list(project.tickets.select_related("category", "assigned_member").order_by("id"))
    complete = [ticket for ticket in children if ticket.status in COMPLETED_STATUSES]
    if project.progress_mode == BusinessProject.ProgressMode.WEIGHTED:
        total_weight = sum(max(int(t.progress_weight or 0), 0) for t in children)
        done_weight = sum(max(int(t.progress_weight or 0), 0) for t in complete)
        progress = round((done_weight / total_weight) * 100, 2) if total_weight else 0.0
    else:
        progress = round((len(complete) / len(children)) * 100, 2) if children else 0.0

    projected_revenue = sum(int(t.projected_customer_amount_cents or 0) for t in children)
    projected_cost = sum(int(t.projected_cost_cents or 0) for t in children)
    actual_revenue = sum(int(t.actual_customer_amount_cents or 0) for t in children)
    actual_cost = sum(int(t.actual_cost_cents or 0) for t in children)

    def pnl(revenue, cost):
        profit = revenue - cost
        return {
            "revenue": _money(revenue), "cost": _money(cost),
            "gross_profit": _money(profit),
            "gross_margin_percent": round((profit / revenue) * 100, 2) if revenue else 0.0,
            "markup_percent": round((profit / cost) * 100, 2) if cost else 0.0,
        }

    return {
        "child_count": len(children),
        "completed_child_count": len(complete),
        "progress_percent": progress,
        "projected": pnl(projected_revenue, projected_cost),
        "actual": pnl(actual_revenue, actual_cost),
    }


class ProjectChildTicketSerializer(serializers.ModelSerializer):
    projected_profit_cents = serializers.SerializerMethodField()
    actual_profit_cents = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id", "ticket_code", "project", "parent_ticket", "business_customer",
            "work_title", "work_scope", "status", "category", "assigned_member",
            "service_address", "service_zip", "scheduled_at", "completed_at",
            "progress_weight", "customer_visible", "customer_status_label",
            "projected_customer_amount_cents", "projected_cost_cents", "projected_profit_cents",
            "actual_customer_amount_cents", "actual_cost_cents", "actual_profit_cents",
            "is_imported", "created_at",
        ]
        read_only_fields = ["id", "ticket_code", "project", "business_customer", "is_imported", "created_at", "completed_at"]

    def get_projected_profit_cents(self, obj):
        return int(obj.projected_customer_amount_cents or 0) - int(obj.projected_cost_cents or 0)

    def get_actual_profit_cents(self, obj):
        return int(obj.actual_customer_amount_cents or 0) - int(obj.actual_cost_cents or 0)


class BusinessProjectSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    rollup = serializers.SerializerMethodField()
    children = ProjectChildTicketSerializer(source="tickets", many=True, read_only=True)

    class Meta:
        model = BusinessProject
        fields = [
            "id", "business", "business_customer", "customer_name", "primary_ticket",
            "title", "description", "status", "billing_mode", "progress_mode",
            "customer_status_note", "rollup", "children", "created_by", "updated_by",
            "created_at", "updated_at", "completed_at",
        ]
        read_only_fields = [
            "id", "business", "customer_name", "rollup", "children", "created_by",
            "updated_by", "created_at", "updated_at", "completed_at",
        ]

    def get_customer_name(self, obj):
        c = obj.business_customer
        return "" if not c else (c.name or c.company_name or c.email or c.phone or f"Customer {c.id}")

    def get_rollup(self, obj):
        return project_rollup(obj)
