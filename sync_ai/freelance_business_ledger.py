"""Founder-only, account-scoped freelance operations ledger.

A manual ledger, not a live Upwork feed. Store non-confidential operational
metadata and self-recorded expense amounts, never credentials or client files.
Events remain append-only in the existing AuditLog model.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from .freelance_pilot_views import FounderFreelancePermission, FreelanceThrottle

ADD = "freelance.operations.record.created"
CHANGE = "freelance.operations.record.updated"
STATUS = {"SAVED", "QUALIFIED", "PROPOSAL_DRAFT", "APPLIED", "VIEWED", "INTERVIEW",
          "OFFERED", "HIRED", "IN_PROGRESS", "SUBMITTED", "PAID", "DECLINED",
          "WITHDRAWN", "CLOSED"}
CATEGORY = {"JOB", "EXPENSE"}
COST_TYPE = {"CONNECTS", "UPWORK_FEE", "AI", "SOFTWARE", "OTHER"}
MAX_RECORDS = 200

def money(value):
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError("Enter a valid monetary amount.")
    if not amount.is_finite() or not Decimal("0") <= amount <= Decimal("1000000"):
        raise ValidationError("Amount out of range.")
    if amount != amount.quantize(Decimal(".01")):
        raise ValidationError("Maximum two decimal places.")
    return str(amount.quantize(Decimal(".01")))

def validate(data, partial=False):
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object.")
    allowed = {"category","title","upwork_job_id","url","status","expected_gross",
               "contract_gross","billed_gross","paid_gross","connects_used","connects_unit_cost",
               "cash_spent","cost_type","estimated_hours","source","notes"}
    if set(data)-allowed:
        raise ValidationError("Unsupported ledger fields.")
    fields = {}
    for key, val in data.items():
        if key in {"title","upwork_job_id","url","notes"}:
            if not isinstance(val,str) or len(val)>(140 if key=="title" else 500 if key=="notes" else 250):
                raise ValidationError(f"Invalid {key}.")
            fields[key] = val.strip()
        elif key=="category":
            if val not in CATEGORY:raise ValidationError("Invalid record category.")
            fields[key]=val
        elif key=="status":
            if val not in STATUS:raise ValidationError("Invalid application status.")
            fields[key]=val
        elif key=="cost_type":
            if val not in COST_TYPE:raise ValidationError("Invalid expense type.")
            fields[key]=val
        elif key in {"expected_gross","contract_gross","billed_gross","paid_gross","connects_unit_cost","cash_spent"}:
            fields[key]=money(val)
        elif key=="connects_used":
            if type(val) is not int or not 0<=val<=1000:raise ValidationError("Connects spent must be an integer from 0 to 1000.")
            fields[key]=val
        elif key=="estimated_hours":
            try: hours=Decimal(str(val))
            except (ValueError,TypeError,InvalidOperation):raise ValidationError("Invalid estimated hours.")
            if not hours.is_finite() or not 0<=hours<=10000:raise ValidationError("Invalid estimated hours.")
            fields[key]=float(hours)
        elif key=="source":
            if val not in {"MANUAL","CHATGPT_VERIFIED","UPWORK_CONFIRMED"}:
                raise ValidationError("Invalid provenance.")
            # Never let the website mark a financial number as verified by Upwork.
            if val!="MANUAL":raise ValidationError("Only manual records can be created by this endpoint.")
            fields[key]=val
    if not partial:
        if not fields.get("title"):raise ValidationError("Title required.")
        fields.setdefault("category","JOB")
        fields.setdefault("status","SAVED")
        fields["source"]="MANUAL"
    if "url" in fields and fields["url"]:
        parsed = urlsplit(fields["url"])
        if parsed.scheme != "https" or parsed.hostname != "www.upwork.com" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValidationError("Only official HTTPS Upwork posting links are accepted.")
    return fields

def snapshot(owner):
    records={}
    events=AuditLog.objects.filter(actor=owner,action__in=[ADD,CHANGE]).order_by("id").only("action","metadata","created_at")
    for event in events:
        meta=event.metadata if isinstance(event.metadata,dict) else {}
        try: rid=str(UUID(str(meta.get("record_id",""))))
        except (ValueError,TypeError,AttributeError):continue
        fields=meta.get("fields",{})
        if not isinstance(fields,dict):continue
        if event.action==ADD:
            if rid not in records:
                records[rid]={"id":rid,"created_at":event.created_at.isoformat(),"updated_at":event.created_at.isoformat(),**fields}
        elif rid in records:
            records[rid].update(fields)
            records[rid]["updated_at"]=event.created_at.isoformat()
    return sorted(records.values(),key=lambda r:r["created_at"],reverse=True)

def summary(records):
    jobs=[r for r in records if r.get("category")=="JOB"]
    expenses=[r for r in records if r.get("category")=="EXPENSE"]
    total=lambda key,rows:sum((Decimal(str(r.get(key,"0"))) for r in rows),Decimal("0"))
    cash=total("cash_spent",expenses)+total("cash_spent",jobs)
    return {"tracked_jobs":len(jobs),"applications":sum(r.get("status") in {"APPLIED","VIEWED","INTERVIEW","OFFERED","HIRED","IN_PROGRESS","SUBMITTED","PAID","DECLINED"} for r in jobs),
            "offers":sum(r.get("status")=="OFFERED" for r in jobs),
            "hired":sum(r.get("status") in {"HIRED","IN_PROGRESS","SUBMITTED","PAID"} for r in jobs),
            "declined":sum(r.get("status")=="DECLINED" for r in jobs),
            "potential_gross":str(total("expected_gross",jobs)),
            "contracted_gross":str(total("contract_gross",jobs)),
            "billed_gross":str(total("billed_gross",jobs)),
            "received_gross":str(total("paid_gross",jobs)),
            "cash_expenses":str(cash),
            "recorded_net_cash":str(total("paid_gross",jobs)-cash),
            "connects_used":sum(int(r.get("connects_used",0)) for r in records),
            "source":"MANUAL","verified_upwork_feed":False}

class FreelanceBusinessLedgerView(APIView):
    permission_classes=[IsAuthenticated,FounderFreelancePermission]
    parser_classes=[JSONParser]
    throttle_classes=[FreelanceThrottle]
    def get(self,request):
        data=snapshot(request.user)
        return Response({"records":data,"summary":summary(data),"sync_status":"NOT_CONNECTED",
                         "note":"Manual records only; ChatGPT Upwork plugin authorization is not a server integration."})
    def post(self,request):
        fields=validate(request.data)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            owner=get_user_model().objects.select_for_update().get(pk=request.user.pk)
            existing=snapshot(owner)
            if len(existing)>=MAX_RECORDS:return Response({"detail":"Ledger pilot limit reached."},status=429)
            job_id=fields.get("upwork_job_id","")
            if job_id and fields.get("category")=="JOB" and any(r.get("category")=="JOB" and r.get("upwork_job_id")==job_id for r in existing):
                return Response({"detail":"This Upwork job is already tracked."},status=409)
            rid=str(uuid4())
            AuditLog.objects.create(actor=owner,action=ADD,metadata={"record_id":rid,"fields":fields})
        return Response({"record_id":rid,"records":snapshot(request.user)},status=201)

class FreelanceBusinessRecordView(APIView):
    permission_classes=[IsAuthenticated,FounderFreelancePermission]
    parser_classes=[JSONParser]
    throttle_classes=[FreelanceThrottle]
    def patch(self,request,record_id):
        fields=validate(request.data,partial=True)
        if "category" in fields or "source" in fields:
            return Response({"detail":"Category and provenance cannot be modified."},status=400)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            owner=get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if str(record_id) not in {r["id"] for r in snapshot(owner)}:
                return Response({"detail":"Not found."},status=404)
            AuditLog.objects.create(actor=owner,action=CHANGE,metadata={"record_id":str(record_id),"fields":fields})
        data=snapshot(request.user)
        return Response({"records":data,"summary":summary(data)})
