# backend/user_accounts/viewsets/pm_overview_summary.py
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _has_field(model, field: str) -> bool:
    try:
        model._meta.get_field(field)
        return True
    except Exception:
        return False


def _scope_business(qs, business_id: int | None):
    """
    Best-effort business scoping via X-Business-Id header.
    If model has business/business_id, filter it. Otherwise, return qs as-is.
    """
    if not business_id:
        return qs

    m = qs.model
    if _has_field(m, "business_id"):
        return qs.filter(business_id=business_id)
    if _has_field(m, "business"):
        return qs.filter(business_id=business_id)
    return qs


def _import_pm_document_model():
    """
    Your project file naming differs (pm_document vs pm_documents).
    Import robustly with fallbacks so this endpoint doesn't crash.
    """
    # 1) Most common in this codebase style (based on pm_property/pm_unit/etc)
    try:
        from user_accounts.models.pm_document import PMDocument  # type: ignore
        return PMDocument
    except Exception:
        pass

    # 2) If someone named it pm_documents
    try:
        from user_accounts.models.pm_documents import PMDocument  # type: ignore
        return PMDocument
    except Exception:
        pass

    # 3) If models/__init__.py exports it
    try:
        from user_accounts.models import PMDocument  # type: ignore
        return PMDocument
    except Exception:
        return None


def _import_section8_model():
    """
    Section 8 model path might vary; keep it optional.
    """
    try:
        from user_accounts.models.pm_section8 import PMSection8Case  # type: ignore
        return PMSection8Case
    except Exception:
        try:
            from user_accounts.models import PMSection8Case  # type: ignore
            return PMSection8Case
        except Exception:
            return None


class PMOverviewSummaryAPIView(APIView):
    """
    GET /api/v1/pm/overview/summary/

    Portfolio KPI rollups for the PM Overview tab.

    Computes NOW (based on existing PM models):
      - counts: properties/units/tenants/invites/docs
      - occupancy (best effort using tenant.unit)
      - missing leases per unit (doc_type == LEASE)
      - section8 not-ready count (packet_ready false)
      - inspections next 14 days (inspection_scheduled_date within range & not completed)

    Returns QUEUED (null for now):
      - cashflow in/out MTD
      - delinquencies + due soon
      (needs PMRentSchedule + PMRentPayment / ledger module)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Header business scope
        biz_id = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
        try:
            biz_id_int = int(biz_id) if biz_id else None
        except Exception:
            biz_id_int = None

        now = timezone.now()
        today = now.date()

        # Import core PM models (these are confirmed by your traceback)
        from user_accounts.models import PMInvite, PMProperty, PMTenant, PMUnit  # noqa

        PMDocument = _import_pm_document_model()
        PMSection8Case = _import_section8_model()

        # --- Base querysets ---
        properties_qs = _scope_business(PMProperty.objects.all(), biz_id_int)
        units_qs = _scope_business(PMUnit.objects.all(), biz_id_int)
        tenants_qs = _scope_business(PMTenant.objects.all(), biz_id_int)
        invites_qs = _scope_business(PMInvite.objects.all(), biz_id_int)

        docs_count = None
        docs_qs = None
        if PMDocument is not None:
            docs_qs = _scope_business(PMDocument.objects.all(), biz_id_int)
            docs_count = docs_qs.count()

        properties_count = properties_qs.count()
        units_count = units_qs.count()
        tenants_count = tenants_qs.count()
        invites_count = invites_qs.count()

        # --- Occupancy (best effort) ---
        occupied_units = 0
        vacant_units = 0
        occupancy_pct = None

        if units_count > 0 and _has_field(PMTenant, "unit"):
            occupied_unit_ids = (
                tenants_qs.exclude(unit__isnull=True)
                .values_list("unit_id", flat=True)
                .distinct()
            )
            occupied_units = len(list(occupied_unit_ids))
            vacant_units = max(0, units_count - occupied_units)
            occupancy_pct = round((occupied_units / units_count) * 100, 1)

        # --- Missing leases per unit (doc_type == LEASE, unit not null) ---
        missing_leases_units = None
        if docs_qs is not None and units_count > 0:
            if _has_field(PMDocument, "doc_type") and _has_field(PMDocument, "unit"):
                lease_docs = docs_qs.filter(doc_type__iexact="LEASE").exclude(unit__isnull=True)
                lease_unit_ids = set(lease_docs.values_list("unit_id", flat=True).distinct())
                all_unit_ids = set(units_qs.values_list("id", flat=True))
                missing_leases_units = max(0, len(all_unit_ids - lease_unit_ids))

        # --- Upcoming move-outs (optional best effort) ---
        upcoming_moveouts_30 = None
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

        # --- Section 8 KPIs (optional) ---
        section8_not_ready_count = None
        inspections_next_14_count = None

        if PMSection8Case is not None:
            s8_qs = _scope_business(PMSection8Case.objects.all(), biz_id_int)

            if _has_field(PMSection8Case, "packet_ready"):
                section8_not_ready_count = s8_qs.filter(Q(packet_ready=False) | Q(packet_ready__isnull=True)).count()

            sched_field = "inspection_scheduled_date" if _has_field(PMSection8Case, "inspection_scheduled_date") else None
            done_field = "inspection_completed_date" if _has_field(PMSection8Case, "inspection_completed_date") else None
            if sched_field:
                start = today
                end = today + timedelta(days=14)
                q = Q(**{f"{sched_field}__isnull": False, f"{sched_field}__gte": start, f"{sched_field}__lte": end})
                if done_field:
                    q &= Q(**{f"{done_field}__isnull": True})
                inspections_next_14_count = s8_qs.filter(q).count()

        payload = {
            "as_of": now.isoformat(),

            # Counts
            "properties_count": properties_count,
            "units_count": units_count,
            "tenants_count": tenants_count,
            "invites_count": invites_count,
            "documents_count": docs_count,  # null if PMDocument import not found

            # Portfolio KPIs
            "occupancy_pct": occupancy_pct,  # number or null
            "occupied_units": occupied_units,
            "vacant_units": vacant_units,
            "missing_leases_units": missing_leases_units,  # number or null
            "upcoming_moveouts_30": upcoming_moveouts_30,  # number or null

            # Section 8 KPIs
            "section8_not_ready_count": section8_not_ready_count,   # number or null
            "inspections_next_14_count": inspections_next_14_count, # number or null

            # Money / Delinquencies (queued until rent ledger exists)
            "cash_in_mtd": None,
            "cash_out_mtd": None,
            "delinquent_count": None,
            "delinquent_amount": None,
            "due_next_7_count": None,
            "due_next_7_amount": None,
        }

        return Response(payload)
