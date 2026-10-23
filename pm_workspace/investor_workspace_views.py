"""Accepted investor relationships: only owned properties, approved statements and shared files."""
import hashlib
import secrets
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PMWorkspace, PMProperty, PMUnit
from .owner_models import PMPropertyOwner
from .access_models import PMInvestorGrant, PMInvestorStatement, PMInvestorDocumentShare
from .document_models import PMPropertyDocument
from .workorder_models import PMWorkOrder
from .communication_models import PMConversation, PMConversationMessage

def _ws(request):
 qs=PMWorkspace.objects.filter(owner=request.user,is_active=True)
 wid=request.headers.get("X-PM-Workspace-ID")
 ws=qs.filter(id=wid).first() if wid else qs.first()
 if not ws:raise PermissionDenied("Portfolio owner access required.")
 return ws

def _grants(user):
 return PMInvestorGrant.objects.filter(user=user,status="ACCEPTED",workspace__is_active=True).select_related("workspace","property_owner")

def _grant(g):
 return {"id":g.id,"owner_id":g.property_owner_id,"owner_name":g.property_owner.name,
         "email":g.email,"status":g.status,"property_ids":list(
          g.property_owner.properties.filter(workspace=g.workspace).values_list("id",flat=True))}

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def investor_invites(request):
 ws=_ws(request)
 if request.method=="GET":
  return Response({"investors":[_grant(g) for g in PMInvestorGrant.objects.filter(
    workspace=ws).select_related("property_owner")]})
 owner=PMPropertyOwner.objects.filter(workspace=ws,pk=request.data.get("owner_id")).first()
 if not owner or not owner.email:return Response({"detail":"Select an owner with a contact email."},status=400)
 if PMInvestorGrant.objects.filter(workspace=ws,property_owner=owner,status="ACCEPTED").exists():
  return Response({"detail":"Already connected. Revoke first to re-invite."},status=409)
 token=secrets.token_urlsafe(28)
 g,_=PMInvestorGrant.objects.update_or_create(workspace=ws,property_owner=owner,
  defaults={"email":owner.email.strip().casefold(),"status":"INVITED","user":None,
            "accepted_at":None,"invite_token_hash":hashlib.sha256(token.encode()).hexdigest(),
            "invite_expires_at":timezone.now()+timedelta(days=14)})
 return Response({"investor":_grant(g),"invitation_code":token,
                  "detail":"Invitation prepared. Share code privately; not emailed automatically."},status=201)

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def revoke_investor(request,grant_id):
 ws=_ws(request)
 g=PMInvestorGrant.objects.filter(workspace=ws,id=grant_id).first()
 if not g:return Response({"detail":"Grant not found."},status=404)
 if request.data.get("status")!="REVOKED":return Response({"detail":"Only revoke is supported."},status=400)
 g.status="REVOKED";g.user=None;g.invite_token_hash=""
 g.save(update_fields=["status","user","invite_token_hash","updated_at"])
 return Response({"revoked":True})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def investor_accept(request):
 code=str(request.data.get("code") or "")
 if len(code)<24:return Response({"detail":"Invalid invite code."},status=400)
 h=hashlib.sha256(code.encode()).hexdigest()
 with transaction.atomic():
  g=PMInvestorGrant.objects.select_for_update().filter(
    status="INVITED",invite_token_hash=h,invite_expires_at__gt=timezone.now()).first()
  if not g:return Response({"detail":"Invitation invalid or expired."},status=404)
  if str(request.user.email or "").casefold()!=g.email.casefold():
   return Response({"detail":"Log in using the invited investor email address."},status=403)
  g.user=request.user;g.status="ACCEPTED";g.accepted_at=timezone.now();g.invite_token_hash=""
  g.save(update_fields=["user","status","accepted_at","invite_token_hash","updated_at"])
 return Response({"investor":_grant(g),"detail":"Investor portfolio connected."})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def investor_portfolios(request):
 items=[]
 for g in _grants(request.user):
  props=list(g.property_owner.properties.filter(workspace=g.workspace))
  ids=[p.id for p in props]
  statements=PMInvestorStatement.objects.filter(workspace=g.workspace,property_owner=g.property_owner,
     property_id__in=ids,status__in=["SHARED","PAID"]).order_by("-period")
  docs=PMInvestorDocumentShare.objects.filter(workspace=g.workspace,property_owner=g.property_owner,
     document__property_id__in=ids).select_related("document")
  items.append({"grant_id":g.id,"company":g.workspace.name,"owner_name":g.property_owner.name,
   "properties":[{
    "id":p.id,"name":p.name,"address":p.address,"health":p.status,
    "units":PMUnit.objects.filter(property=p).count(),
    "occupied":PMUnit.objects.filter(property=p,availability="OCCUPIED").count(),
    "open_work_orders":PMWorkOrder.objects.filter(property=p).exclude(
      status__in=["COMPLETED","CANCELLED"]).count()
   } for p in props],
   "statements":[{
    "id":s.id,"property_id":s.property_id,"period":s.period,"status":s.status,
    "rent_received":str(s.rent_received),"management_fees":str(s.management_fees),
    "expenses":str(s.expenses),"reserve_change":str(s.reserve_change),
    "owner_payout":str(s.owner_payout),"payout_date":str(s.payout_date) if s.payout_date else None,
    "reference":s.payout_reference,
   } for s in statements],
   "documents":[{"id":x.document_id,"title":x.document.title,
      "property_id":x.document.property_id,"category":x.document.category} for x in docs],
  })
 return Response({"portfolios":items,"notice":"Financials only show shared statements and explicitly recorded payout status; no draft statements or unrelated tenant documents are exposed."})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def investor_file(request,document_id):
 owner_ids=list(_grants(request.user).values_list("property_owner_id",flat=True))
 record=PMInvestorDocumentShare.objects.filter(
  property_owner_id__in=owner_ids,document_id=document_id).select_related(
   "property_owner","workspace","document").first()
 if not record or record.workspace_id!=record.document.workspace_id or not (
   record.property_owner.properties.filter(id=record.document.property_id).exists()):
  return Response({"detail":"File not shared with this account."},status=404)
 if not record.document.document:return Response({"detail":"No file uploaded."},status=404)
 try:return FileResponse(record.document.document.open("rb"),as_attachment=True)
 except OSError:return Response({"detail":"Document unavailable."},status=503)

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def owner_statements(request):
 ws=_ws(request)
 if request.method=="GET":
  qs=PMInvestorStatement.objects.filter(workspace=ws)
  return Response({"statements":[{"id":s.id,"property_id":s.property_id,"owner_id":s.property_owner_id,
    "period":s.period,"status":s.status,"owner_payout":str(s.owner_payout)} for s in qs[:300]]})
 owner=PMPropertyOwner.objects.filter(workspace=ws,pk=request.data.get("owner_id")).first()
 prop=PMProperty.objects.filter(workspace=ws,pk=request.data.get("property_id")).first()
 if not owner or not prop or not owner.properties.filter(id=prop.id).exists():
  return Response({"detail":"Owner must be linked to this property."},status=400)
 period=str(request.data.get("period") or "")
 if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
  return Response({"detail":"Period must be YYYY-MM."},status=400)
 amounts={}
 fields=("rent_received","management_fees","expenses","reserve_change","owner_payout")
 for key in fields:
  try:
   x=Decimal(str(request.data.get(key,"0"))).quantize(Decimal("0.01"))
   if not x.is_finite() or abs(x)>999999999:raise ValueError()
   amounts[key]=x
  except (TypeError,ValueError,InvalidOperation):
   return Response({"detail":"Invalid "+key},status=400)
 if amounts["owner_payout"]!=amounts["rent_received"]-amounts["management_fees"]-amounts["expenses"]+amounts["reserve_change"]:
  return Response({"detail":"Payout must reconcile to rent received minus fees and expenses plus reserve change."},status=400)
 stage=str(request.data.get("status") or "DRAFT")
 if stage not in ("DRAFT","SHARED","PAID"):return Response({"detail":"Invalid status."},status=400)
 payout_date=None
 reference=""
 if stage=="PAID":
  try:payout_date=date.fromisoformat(str(request.data.get("payout_date") or ""))
  except ValueError:return Response({"detail":"Paid payout requires date."},status=400)
  reference=str(request.data.get("reference") or "").strip()[:120]
  if not reference:return Response({"detail":"Paid payout requires a payment reference."},status=400)
 data={**amounts,"status":stage,"payout_date":payout_date,"payout_reference":reference,
       "notes":str(request.data.get("notes") or "")[:1800]}
 s,created=PMInvestorStatement.objects.update_or_create(
   workspace=ws,property_owner=owner,property=prop,period=period,defaults=data)
 return Response({"id":s.id,"status":s.status,"payout":str(s.owner_payout)},status=201 if created else 200)

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def owner_shared_files(request):
 ws=_ws(request)
 if request.method=="GET":
  qs=PMInvestorDocumentShare.objects.filter(workspace=ws)
  return Response({"shares":[{"id":x.id,"owner_id":x.property_owner_id,"document_id":x.document_id} for x in qs]})
 owner=PMPropertyOwner.objects.filter(workspace=ws,pk=request.data.get("owner_id")).first()
 document=PMPropertyDocument.objects.filter(workspace=ws,pk=request.data.get("document_id")).first()
 if not owner or not document or not owner.properties.filter(id=document.property_id).exists():
  return Response({"detail":"Owner/document/property relationship must be verified."},status=400)
 if document.category=="IDENTITY_TAX":
  return Response({"detail":"Identity and tax files cannot be shared through this portal."},status=403)
 share,created=PMInvestorDocumentShare.objects.get_or_create(
   workspace=ws,property_owner=owner,document=document)
 return Response({"id":share.id,"shared":True},status=201 if created else 200)

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def owner_unshare(request,share_id):
 ws=_ws(request)
 deleted=PMInvestorDocumentShare.objects.filter(workspace=ws,id=share_id).delete()[0]
 return Response({"unshared":bool(deleted)})

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def investor_messages(request):
 grants=list(_grants(request.user))
 if request.method=="GET":
  ids=[g.property_owner_id for g in grants]
  qs=PMConversation.objects.filter(property_owner_id__in=ids,category="INVESTOR",
         internal_only=False,workspace__in=[g.workspace for g in grants])
  return Response({"messages":[{"id":m.id,"subject":m.subject,"status":m.status,
      "property_id":m.property_id} for m in qs[:100]]})
 grant=next((g for g in grants if str(g.id)==str(request.data.get("grant_id"))),None)
 if not grant:return Response({"detail":"Investor access not found."},status=403)
 prop=PMProperty.objects.filter(workspace=grant.workspace,pk=request.data.get("property_id")).first()
 if not prop or not grant.property_owner.properties.filter(id=prop.id).exists():
  return Response({"detail":"Property not linked to you."},status=403)
 subject=str(request.data.get("subject") or "").strip()[:180]
 body=str(request.data.get("body") or "").strip()[:3000]
 if len(subject)<3 or not body:return Response({"detail":"Subject and message required."},status=400)
 with transaction.atomic():
  convo=PMConversation.objects.create(workspace=grant.workspace,category="INVESTOR",
     status="WAITING_PM",property=prop,property_owner=grant.property_owner,
     subject=subject,requester_email=grant.email,requester_name=grant.property_owner.name)
  PMConversationMessage.objects.create(conversation=convo,sender=request.user,sender_role="INVESTOR",body=body)
 return Response({"id":convo.id,"detail":"Message added to PM inbox."},status=201)
