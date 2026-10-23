"""Rent-change planning and approval trail.

Planning does not change lease contract rent, the tenant's monthly charge, or
third-party subsidy amounts. Approval documents and effective dates remain
independent records for an explicitly reviewed later ledger update.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace
from .models import PMProperty, PMTenant, PMLease, PMDocumentPacket
from .document_models import PMPropertyDocument

KIND="RENT_CHANGE_PLAN"
STATUSES={"DRAFT","READY_FOR_SIGNATURE","SIGNED","SUBMITTED","UNDER_REVIEW","APPROVED","DENIED","WITHDRAWN","EFFECTIVE"}
SIGNING={"NOT_REQUESTED","PREPARED","SENT_EXTERNALLY","SIGNED_VERIFIED"}
REQUIRED_FIELDS={"tenant_id","current_rent","requested_rent","proposed_effective_date"}
CENT=Decimal("0.01")

def _money(raw):
    try:
        x=Decimal(str(raw)).quantize(CENT)
    except (ValueError,TypeError,InvalidOperation):
        return None
    return x if x.is_finite() and Decimal("0.00") <= x <= Decimal("999999999.99") else None

def _date(raw):
    try:
        value=str(raw)
        parsed=date.fromisoformat(value)
        return parsed if parsed.isoformat()==value else None
    except (TypeError,ValueError):
        return None

def _plan_json(plan):
    return {"id":plan.id,"created_at":plan.created_at.isoformat(),"updated_at":plan.updated_at.isoformat(),
            **(plan.field_data or {})}

def _scoped_property(request,property_id):
    workspace=_workspace(request)
    prop=PMProperty.objects.filter(workspace=workspace,pk=property_id).first()
    return workspace,prop

def _evaluate(fields, lease, assistance, today):
    effective=_date(fields.get("proposed_effective_date"))
    notice=_date(fields.get("notice_date"))
    anniversary=_date(fields.get("hap_anniversary_date"))
    initial_end=lease.end_date if lease else None
    if lease and lease.section8 and lease.start_date and not initial_end:
        initial_end=lease.start_date.replace(year=lease.start_date.year + 1)-timedelta(days=1) if lease.start_date.month!=2 or lease.start_date.day!=29 else date(lease.start_date.year+1,2,28)
    if assistance:
        required_days=60
        suggested=anniversary-timedelta(days=90) if anniversary else None
        request_due=anniversary-timedelta(days=60) if anniversary else None
    else:
        required_days=None
        suggested=None
        request_due=None
    earliest_notice=(notice+timedelta(days=required_days)) if notice and required_days else None
    warnings=[]
    if effective and earliest_notice and effective < earliest_notice:
        warnings.append("Effective date is earlier than 60 days after notice to the assistance administrator.")
    if assistance and not anniversary:
        warnings.append("Confirm the HAP contract anniversary with the local administrator; timing is provisional.")
    if assistance and initial_end and effective and effective <= initial_end:
        warnings.append("Proposed increase falls in the initial contract term; review program requirements.")
    if not notice:
        warnings.append("No actual notice date recorded. Do not assume notice has been delivered.")
    if assistance and fields.get("administrator_approval_status") != "APPROVED":
        warnings.append("Assistance administrator approval has not been confirmed; do not activate a new rent.")
    return {
        "notice_period_days":required_days, "recommended_prepare_by":str(suggested) if suggested else None,
        "administrator_request_deadline":str(request_due) if request_due else None,
        "earliest_by_notice":str(earliest_notice) if earliest_notice else None,
        "initial_term_end":str(initial_end) if initial_end else None,
        "warnings":warnings,
        "approval_required":bool(assistance),
        "rent_will_change_automatically":False,
    }

def _validate_fields(raw, tenant, lease, existing=None):
    data=dict(existing or {})
    if not isinstance(raw,dict):
        raise ValueError("Enter valid rent change data.")
    permitted={"tenant_id","current_rent","requested_rent","proposed_effective_date","notice_date",
               "hap_anniversary_date","administrator","administrator_form_url","status","notes",
               "tenant_signature_status","owner_signature_status","administrator_approval_status",
               "approval_document_id","approval_date","approved_rent","source_document_id"}
    if set(raw)-permitted:
        raise ValueError("Unsupported rent-change field.")
    data.update(raw)
    for key in ("current_rent","requested_rent","approved_rent"):
        if key=="approved_rent" and data.get(key) in (None,""):
            data[key]=""
            continue
        amount=_money(data.get(key))
        if amount is None:
            raise ValueError("Rent amounts must be valid nonnegative numbers.")
        data[key]=str(amount)
    if Decimal(data["requested_rent"]) <= Decimal(data["current_rent"]):
        raise ValueError("For an increase, requested rent must exceed current rent.")
    if not _date(data.get("proposed_effective_date")):
        raise ValueError("Enter a proposed effective date.")
    for key in ("notice_date","hap_anniversary_date","approval_date"):
        if data.get(key) and not _date(data[key]):
            raise ValueError("Dates must be YYYY-MM-DD.")
    for key in ("tenant_signature_status","owner_signature_status"):
        if data.get(key) not in SIGNING:
            raise ValueError("Invalid signature progress.")
    for key in ("status",):
        if data.get(key) not in STATUSES:
            raise ValueError("Invalid workflow state.")
    if len(str(data.get("notes") or ""))>2500:
        raise ValueError("Notes too long.")
    if data["status"] in {"APPROVED","EFFECTIVE"}:
        if data.get("administrator_approval_status") != "APPROVED" and lease and lease.section8:
            raise ValueError("Record written assistance-administrator approval first.")
        if not _date(data.get("approval_date")) or not _money(data.get("approved_rent")):
            raise ValueError("Approved rent and approval date are required.")
        if not data.get("approval_document_id"):
            raise ValueError("Attach the approval document before marking approved.")
    return data

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def property_rent_change_plans(request,property_id):
    workspace,prop=_scoped_property(request,property_id)
    if not prop:
        return Response({"detail":"Property not found."},status=404)
    plans=[p for p in PMDocumentPacket.objects.filter(workspace=workspace,packet_type=KIND).select_related("tenant","lease")
           if (p.field_data or {}).get("property_id")==prop.id]
    if request.method=="GET":
        return Response({"plans":[{**_plan_json(p),"schedule":_evaluate(p.field_data,p.lease,bool(p.lease and p.lease.section8),timezone.localdate())} for p in plans]})
    tenant=PMTenant.objects.filter(workspace=workspace,pk=request.data.get("tenant_id")).first()
    if not tenant:
        return Response({"detail":"Select an existing tenant in this portfolio first."},status=400)
    lease=PMLease.objects.filter(workspace=workspace,tenant=tenant).order_by("-start_date","-id").first()
    initial={
        "tenant_id":tenant.id,"property_id":prop.id,
        "current_rent":str(lease.monthly_rent if lease else tenant.monthly_rent or "0.00"),
        "requested_rent":"",
        "approved_rent":"","proposed_effective_date":"","notice_date":"","hap_anniversary_date":"",
        "administrator":str(lease.housing_authority if lease else ""),
        "administrator_form_url":"","status":"DRAFT","notes":"",
        "tenant_signature_status":"NOT_REQUESTED","owner_signature_status":"NOT_REQUESTED",
        "administrator_approval_status":"UNKNOWN","approval_date":"","approval_document_id":None,"source_document_id":None,
    }
    payload={k:v for k,v in request.data.items() if k in set(initial) - {"property_id"}}
    try: data=_validate_fields(payload,tenant,lease,{**initial,**payload})
    except ValueError as exc:return Response({"detail":str(exc)},status=400)
    plan=PMDocumentPacket.objects.create(
        workspace=workspace,tenant=tenant,lease=lease,packet_type=KIND,
        template_name="Rent increase approval workflow",field_data=data,state_code=prop.state,
    )
    return Response({"plan":_plan_json(plan),"schedule":_evaluate(data,lease,bool(lease and lease.section8),timezone.localdate())},status=201)

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def update_rent_change_plan(request,property_id,plan_id):
    workspace,prop=_scoped_property(request,property_id)
    if not prop:
        return Response({"detail":"Property not found."},status=404)
    plan=PMDocumentPacket.objects.select_for_update().filter(workspace=workspace,pk=plan_id,packet_type=KIND).select_related("tenant","lease").first()
    if not plan or (plan.field_data or {}).get("property_id")!=prop.id:
        return Response({"detail":"Rent increase plan not found."},status=404)
    if "tenant_id" in request.data and str(request.data["tenant_id"])!=str(plan.tenant_id):
        return Response({"detail":"Cannot change the tenant of an existing rent plan."},status=400)
    if request.data.get("approval_document_id"):
        if not PMPropertyDocument.objects.filter(workspace=workspace,property=prop,pk=request.data["approval_document_id"]).exists():
            return Response({"detail":"Attach a document from this property."},status=400)
    try: updated=_validate_fields(request.data,plan.tenant,plan.lease,plan.field_data)
    except ValueError as exc: return Response({"detail":str(exc)},status=400)
    history=list(updated.get("history") or [])
    history.append({"at":timezone.now().isoformat(),"actor":request.user.pk,
                    "old_status":(plan.field_data or {}).get("status"),"new_status":updated.get("status")})
    updated["history"]=history[-150:]
    plan.field_data=updated
    plan.save(update_fields=["field_data","updated_at"])
    return Response({"plan":_plan_json(plan),"schedule":_evaluate(updated,plan.lease,bool(plan.lease and plan.lease.section8),timezone.localdate())})
