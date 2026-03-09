# backend/pm/api/overview_summary.py
from __future__ import annotations

from datetime import timedelta

from django.apps import apps
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _scope_business(qs, business_id):
    """
    Best-effort business scoping:
    - If model has business FK/field, filter by it.
    - Otherwise return queryset unfiltered.
    """
    if not business_id:
        return qs

    m = qs.model
    if _has_field(m, "business_id"):
        return qs.filter(business_id=business_id)
    if _has_field(m, "business"):
        return qs.filter(business_id=business_id)
    return qs


def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


class PMOverviewSummaryView(APIView):
    """
    GET /api/v1/pm/overview/summary/
    Requires: Authorization + X-Business-Id
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        biz_id = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
        try:
            biz_id_int = int(biz_id) if biz_id else None
        except Exception:
            biz_id_int = None

        now = timezone.now()
        today = now.date()

        PMProperty = _get_model("pm", "PMProperty")
        PMUnit = _get_model("pm", "PMUnit")
        PMTenant = _get_model("pm", "PMTenant")
        PMInvite = _get_model("pm", "PMInvite")
        PMDocument = _get_model("pm", "PMDocument")
        Section8Case = _get_model("pm", "Section8Case")

        # --- Base counts ---
        properties_qs = _scope_business(PMProperty.objects.all(), biz_id_int) if PMProperty else None
        units_qs = _scope_business(PMUnit.objects.all(), biz_id_int) if PMUnit else None
        tenants_qs = _scope_business(PMTenant.objects.all(), biz_id_int) if PMTenant else None
        invites_qs = _scope_business(PMInvite.objects.all(), biz_id_int) if PMInvite else None
        docs_qs = _scope_business(PMDocument.objects.all(), biz_id_int) if PMDocument else None

        properties_count = properties_qs.count() if properties_qs is not None else 0
        units_count = units_qs.count() if units_qs is not None else 0
        tenants_count = tenants_qs.count() if tenants_qs is not None else 0
        invites_count = invites_qs.count() if invites_qs is not None else 0
        documents_count = docs_qs.count() if docs_qs is not None else 0

        # --- Occupancy ---
        occupied_units = 0
        vacant_units = 0
        occupancy_pct = None

        if units_qs is not None and tenants_qs is not None and units_count > 0:
            if _has_field(PMTenant, "unit"):
                occupied_unit_ids = (
                    tenants_qs.exclude(unit__isnull=True)
                    .values_list("unit_id", flat=True)
                    .distinct()
                )
                occupied_units = len(list(occupied_unit_ids))
            vacant_units = max(0, units_count - occupied_units)
            occupancy_pct = round((occupied_units / units_count) * 100, 1) if units_count else None

        # --- Missing leases ---
        missing_leases_units = None
        if units_qs is not None and PMDocument:
            doc_type_field = "doc_type" if _has_field(PMDocument, "doc_type") else None
            unit_field = "unit" if _has_field(PMDocument, "unit") else None

            if doc_type_field and unit_field and units_count:
                lease_docs = docs_qs.filter(**{f"{doc_type_field}__iexact": "LEASE"}).exclude(unit__isnull=True)
                lease_unit_ids = set(lease_docs.values_list("unit_id", flat=True).distinct())
                all_unit_ids = set(units_qs.values_list("id", flat=True))
                missing_leases_units = max(0, len(all_unit_ids - lease_unit_ids))

        # --- Upcoming move-outs (next 30 days) ---
        upcoming_moveouts_30 = None
        if tenants_qs is not None:
            lease_end_field = None
            for cand in ["lease_end_date", "move_out_date", "end_date"]:
                if _has_field(PMTenant, cand):
                    lease_end_field = cand
                    break

            if lease_end_field:
                start = today
                end = today + timedelta(days=30)
                upcoming_moveouts_30 = tenants_qs.filter(
                    **{
                        f"{lease_end_field}__isnull": False,
                        f"{lease_end_field}__gte": start,
                        f"{lease_end_field}__lte": end,
                    }
                ).count()

        # --- Section 8 KPIs ---
        section8_not_ready_count = None
        inspections_next_14_count = None

        if Section8Case:
            s8_qs = _scope_business(Section8Case.objects.all(), biz_id_int)

            if _has_field(Section8Case, "packet_ready"):
                section8_not_ready_count = s8_qs.filter(Q(packet_ready=False) | Q(packet_ready__isnull=True)).count()

            sched_field = "inspection_scheduled_date" if _has_field(Section8Case, "inspection_scheduled_date") else None
            done_field = "inspection_completed_date" if _has_field(Section8Case, "inspection_completed_date") else None
            if sched_field:
                start = today
                end = today + timedelta(days=14)
                q = Q(**{f"{sched_field}__isnull": False, f"{sched_field}__gte": start, f"{sched_field}__lte": end})
                if done_field:
                    q &= Q(**{f"{done_field}__isnull": True})
                inspections_next_14_count = s8_qs.filter(q).count()

        # --- Work order KPIs (optional) ---
        open_workorders = 0
        overdue_workorders = 0
        WorkOrder = _get_model("user_accounts", "PMWorkOrder") or _get_model("pm", "PMWorkOrder") or _get_model("pm", "WorkOrder")
        if WorkOrder:
            wo_qs = _scope_business(WorkOrder.objects.all(), biz_id_int)

            status_field = "status" if _has_field(WorkOrder, "status") else None
            due_field = "due_date" if _has_field(WorkOrder, "due_date") else None
            completed_field = "completed_at" if _has_field(WorkOrder, "completed_at") else None

            if status_field:
                open_workorders = wo_qs.exclude(**{f"{status_field}__iexact": "COMPLETED"}).count()
            elif completed_field:
                open_workorders = wo_qs.filter(**{f"{completed_field}__isnull": True}).count()

            if due_field:
                q_overdue = Q(**{f"{due_field}__isnull": False, f"{due_field}__lt": today})
                if completed_field:
                    q_overdue &= Q(**{f"{completed_field}__isnull": True})
                overdue_workorders = wo_qs.filter(q_overdue).count()

        payload = {
            "as_of": now.isoformat(),

            "properties_count": properties_count,
            "units_count": units_count,
            "tenants_count": tenants_count,
            "invites_count": invites_count,
            "documents_count": documents_count,

            "occupancy_pct": occupancy_pct,
            "occupied_units": occupied_units,
            "vacant_units": vacant_units,
            "upcoming_moveouts_30": upcoming_moveouts_30,
            "missing_leases_units": missing_leases_units,

            "open_workorders": open_workorders,
            "overdue_workorders": overdue_workorders,

            "section8_not_ready_count": section8_not_ready_count,
            "inspections_next_14_count": inspections_next_14_count,

            # Money (queued)
            "cash_in_mtd": None,
            "cash_out_mtd": None,
            "delinquent_count": None,
            "delinquent_amount": None,
            "due_next_7_count": None,
            "due_next_7_amount": None,
        }

        return Response(payload)
