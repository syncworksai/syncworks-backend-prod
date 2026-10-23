"""Owner-only read model for Property 360. No ledger mutations or inferred receipts."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .access_models import PMStaffTask, PMInvestorStatement
from .communication_models import PMConversation
from .document_models import PMPropertyDocument
from .handoff_views import PACKET_TYPE
from .ledger_audit_views import _allocation, _json_allocation
from .lifecycle_models import PMOccupancy, PMTenantCase
from .models import PMDocumentPacket, PMLease, PMLedgerEntry, PMProject, PMProperty, PMTenant, PMUnit
from .owner_models import PMPropertyOwner
from .views import _requested_workspace
from .workorder_models import PMWorkOrder

def _date(value):
    return value.isoformat() if value else None

def _money(value):
    return str(value or Decimal("0.00"))

def _linked_tenants(workspace, prop):
    """Only explicit unit/occupancy links or unique legacy name match; never match addresses loosely."""
    occupied = list(PMOccupancy.objects.filter(workspace=workspace,property=prop).values_list("tenant_id",flat=True))
    lease_tenants = list(PMLease.objects.filter(workspace=workspace,unit__property=prop).values_list("tenant_id",flat=True))
    explicit = set(occupied + lease_tenants + list(PMTenant.objects.filter(workspace=workspace,property=prop).values_list("id",flat=True)))
    # A legacy tenant stores property_name as free text. Only trust it where the property name is unique.
    name_is_unique = PMProperty.objects.filter(workspace=workspace,name__iexact=prop.name).count() == 1
    named = list(PMTenant.objects.filter(workspace=workspace,property__isnull=True,property_name__iexact=prop.name)
                 .exclude(id__in=explicit)) if name_is_unique else []
    linked = list(PMTenant.objects.filter(workspace=workspace,id__in=explicit).order_by("last_name","first_name"))
    linked.extend(named)
    return linked, set(x.id for x in named), bool(name_is_unique)

def _handoff(workspace,prop):
    packet=PMDocumentPacket.objects.filter(workspace=workspace,packet_type=PACKET_TYPE,
                                           field_data__property_id=prop.id).order_by("-id").first()
    if not packet:
        return {"exists":False,"status":"NOT_STARTED","unresolved_balances":0,"progress":None}
    data=packet.field_data or {}
    balances=data.get("opening_balances") or []
    return {"exists":True,"status":data.get("status","IN_PROGRESS"),
            "unresolved_balances":sum(1 for x in balances if x.get("evidence_status") not in ("DOCUMENTED","RECONCILED")),
            "progress":data.get("status")=="COMPLETED"}

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def property_360(request,property_id):
    workspace=_requested_workspace(request)
    prop=PMProperty.objects.filter(workspace=workspace,pk=property_id).first()
    if not prop:
        return Response({"detail":"Property not found in your portfolio."},status=404)
    today=timezone.localdate()
    tenants,legacy_ids,unique_name=_linked_tenants(workspace,prop)
    tenant_ids=[t.id for t in tenants]
    units=list(PMUnit.objects.filter(workspace=workspace,property=prop).order_by("label"))
    leases=list(PMLease.objects.filter(workspace=workspace,tenant_id__in=tenant_ids)
                .select_related("unit").order_by("-start_date","-id"))
    # Historical financial events are visible as records, not assumed cleared or owed.
    ledger=list(PMLedgerEntry.objects.filter(workspace=workspace,tenant_id__in=tenant_ids).order_by("entry_date","id"))
    by_tenant={}
    for entry in ledger:by_tenant.setdefault(entry.tenant_id,[]).append(entry)
    tenant_balances={}
    for tenant in tenants:
        summary=_json_allocation(_allocation(by_tenant.get(tenant.id,[])))
        tenant_balances[tenant.id]=summary
    outstanding_tenant=sum((Decimal(v["tenant_unpaid"]) for v in tenant_balances.values()),Decimal("0"))
    outstanding_assistance=sum((Decimal(v["housing_unpaid"]) for v in tenant_balances.values()),Decimal("0"))
    work=list(PMWorkOrder.objects.filter(workspace=workspace,property=prop).order_by("-created_at")[:80])
    open_work=[w for w in work if w.status not in ("COMPLETED","CANCELLED")]
    urgent_work=[w for w in open_work if w.priority in ("EMERGENCY","URGENT")]
    projects=list(PMProject.objects.filter(workspace=workspace,property=prop)
                  .exclude(status__in=("COMPLETED","ARCHIVED")).order_by("-updated_at")[:50])
    cases=list(PMTenantCase.objects.filter(workspace=workspace)
               .filter(Q(property=prop)|Q(tenant_id__in=tenant_ids))
               .exclude(status="CLOSED").distinct().order_by("-opened_date")[:30])
    documents=list(PMPropertyDocument.objects.filter(workspace=workspace,property=prop)
                   .order_by("-updated_at")[:80])
    pending_documents=[d for d in documents if d.status in ("DRAFT","PENDING_SIGNATURE","SUBMITTED")]
    owner_records=list(PMPropertyOwner.objects.filter(workspace=workspace,properties=prop).distinct().order_by("name"))
    conversations=PMConversation.objects.filter(workspace=workspace,property=prop).exclude(status="RESOLVED")
    tasks=list(PMStaffTask.objects.filter(workspace=workspace,property=prop)
               .exclude(status__in=("DONE","CANCELED")).select_related("assignee").order_by("due_date","-created_at")[:100])
    requests=list(PMDocumentPacket.objects.filter(workspace=workspace,packet_type="PM_DOCUMENT_REQUEST",
                                                   field_data__property_id=prop.id).order_by("-updated_at")[:120])
    open_requests=[r for r in requests if (r.field_data or {}).get("status") not in ("VERIFIED","CANCELED")]
    past_due_requests=[r for r in open_requests if (r.field_data or {}).get("due_date") and
                       (r.field_data or {})["due_date"]<today.isoformat()]
    shared_statements=PMInvestorStatement.objects.filter(workspace=workspace,property=prop,
                                                         status__in=("SHARED","PAID")).count()
    handoff=_handoff(workspace,prop)
    occupancy_count=sum(1 for u in units if u.availability=="OCCUPIED")
    property_attention=[
        {"key":"urgent","title":"Emergency / urgent work","count":len(urgent_work),"priority":"HIGH",
         "href":f"/pm/properties/{prop.id}?tab=maintenance"},
        {"key":"docs","title":"Documents to review","count":len(pending_documents),"priority":"NORMAL",
         "href":f"/pm/properties/{prop.id}?tab=documents"},
        {"key":"requests","title":"Overdue document requests","count":len(past_due_requests),"priority":"HIGH",
         "href":f"/pm/document-requests?property={prop.id}"},
        {"key":"messages","title":"Open conversations","count":conversations.count(),"priority":"NORMAL",
         "href":f"/pm/properties/{prop.id}?tab=messages"},
        {"key":"tasks","title":"Open team assignments","count":len(tasks),"priority":"NORMAL",
         "href":"/pm/team"},
        {"key":"cases","title":"Open tenant cases","count":len(cases),"priority":"HIGH",
         "href":f"/pm/properties/{prop.id}?tab=tenants"},
    ]
    if handoff["unresolved_balances"]:
        property_attention.append({"key":"handoff","title":"Unresolved opening balances",
             "count":handoff["unresolved_balances"],"priority":"REVIEW",
             "href":f"/pm/handoff?property={prop.id}"})
    if legacy_ids:
        property_attention.append({"key":"links","title":"Verify legacy tenant links","count":len(legacy_ids),
             "priority":"REVIEW","href":f"/pm/properties/{prop.id}?tab=tenants"})
    if not units:
        property_attention.append({"key":"units","title":"Units not configured","count":1,
             "priority":"REVIEW","href":f"/pm/properties/{prop.id}?tab=units"})
    return Response({
        "property":{"id":prop.id,"name":prop.name,"address":prop.address,"city":prop.city,
                    "state":prop.state,"zip":prop.zip,"status":prop.status,"property_type":prop.property_type},
        "links":{"legacy_tenant_ids":sorted(legacy_ids),"property_name_unique":unique_name,
                 "linkage_note":"Historical name-only matching requires owner review. Never create duplicate tenant or property to repair a link."},
        "units":{"total":len(units),"occupied":occupancy_count,"items":[
            {"id":x.id,"label":x.label,"availability":x.availability,"market_rent":_money(x.market_rent)}
            for x in units[:40]]},
        "tenants":[{"id":t.id,"name":(" ".join(x for x in [t.first_name,t.last_name] if x)).strip(),
                    "status":t.status,"unit_label":t.unit_label,"link_status":"REVIEW_NAME_MATCH" if t.id in legacy_ids else "VERIFIED_RELATION",
                    "lease":{"id":l.id,"rent":str(l.monthly_rent),"start":_date(l.start_date),
                             "end":_date(l.end_date),"assistance":l.section8,
                             "administrator":l.housing_authority} if (l:=next((x for x in leases if x.tenant_id==t.id),None)) else None,
                    "posted_tenant_unpaid":tenant_balances[t.id]["tenant_unpaid"],
                    "posted_assistance_unpaid":tenant_balances[t.id]["housing_unpaid"]}
                   for t in tenants],
        "accounting":{"posted_tenant_unpaid":_money(outstanding_tenant),
                      "posted_assistance_unreconciled":_money(outstanding_assistance),
                      "ledger_entries":len(ledger),
                      "verified_owner_payouts":PMInvestorStatement.objects.filter(workspace=workspace,property=prop,
                                                        status="PAID").count(),
                      "notice":"Posted-only ledger analysis; no inference from former-manager statements, holds, disputed deposits, or unmatched receipts."},
        "owners":[{"id":o.id,"name":o.name,"type":o.owner_type} for o in owner_records],
        "operations":{"open_work":len(open_work),"urgent_work":len(urgent_work),
                      "active_projects":len(projects),"open_cases":len(cases),
                      "open_messages":conversations.count(),"open_staff_tasks":len(tasks),
                      "pending_documents":len(pending_documents),"open_requests":len(open_requests),
                      "overdue_requests":len(past_due_requests),"released_investor_statements":shared_statements},
        "handoff":handoff,
        "attention":[x for x in property_attention if x["count"]>0],
        "recent_work":[{"id":w.id,"title":w.title,"status":w.status,"priority":w.priority,
                        "created_at":w.created_at.isoformat()} for w in work[:5]],
        "recent_documents":[{"id":d.id,"title":d.title,"status":d.status,"category":d.category}
                             for d in documents[:5]],
    })
