"""PM document coordination: external email requests and tracked follow-ups.

Not an e-signature service and not a mailbox connector. External recipients do
not receive authenticated file URLs or document contents by email.
All sending requires an explicit authenticated action from the portfolio owner.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace
from .models import PMDocumentPacket, PMProperty
from .document_models import PMPropertyDocument

TYPE = "PM_DOCUMENT_REQUEST"
ROLES = {"TENANT", "OWNER", "PROPERTY_MANAGER", "ASSISTANCE_ADMINISTRATOR", "OTHER"}
ACTIONS = {"SIGNATURE", "APPROVAL", "PROVIDE_DOCUMENT", "PROVIDE_INFORMATION"}
STATES = {"DRAFT","SENT","WAITING_RESPONSE","ACKNOWLEDGED","RECEIVED","VERIFIED",
          "REJECTED","CANCELED"}
CLOSED = {"VERIFIED","CANCELED"}
DOC_KEYWORDS = {
    "ownership_authority": ["proof of ownership", "warranty deed", "special warranty deed",
                            "recorded deed", "ownership documentation"],
    "provider_owner_docs": ["w-9", "w9", "tax identification", "direct deposit form", "voided check"],
    "provider_contract": ["hap contract", "housing assistance payment contract", "tenancy addendum",
                          "rent breakdown", "rent determination"],
    "provider_inspection": ["failed inspection", "inspection report", "deficiency notice", "reinspection"],
    "deposit_accounting": ["security deposit", "deposit ledger"],
    "rent_ledger": ["payment ledger", "rent ledger", "owner ledger"],
    "transition_agreement": ["termination agreement", "management transfer", "change of management"],
}

def _property(request, property_id):
    workspace = _workspace(request)
    prop = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    return workspace, prop

def _get_request(workspace, prop, request_id):
    packet = PMDocumentPacket.objects.select_for_update().filter(
        workspace=workspace, id=request_id, packet_type=TYPE,
        field_data__property_id=prop.id).first()
    return packet

def _valid_mail(value):
    value = str(value or "").strip().lower()
    try:validate_email(value)
    except DjangoValidationError:raise ValueError("Enter a valid recipient email.")
    if len(value)>254:raise ValueError("Recipient email is too long.")
    return value

def _iso(value, allow_blank=True):
    if not value and allow_blank:return ""
    try:
        x = date.fromisoformat(str(value))
        if str(x) != str(value):raise ValueError()
        return str(x)
    except (ValueError,TypeError):raise ValueError("Dates must use YYYY-MM-DD.")

def _string(value,limit=1000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError("Invalid text field.")
    return value.strip()

def _serialize(packet):
    data=packet.field_data or {}
    return {"id":packet.id,"created_at":packet.created_at.isoformat(),
            "updated_at":packet.updated_at.isoformat(), **data}

def _draft(request_data, workspace, prop):
    if not isinstance(request_data,dict):raise ValueError("Provide a request object.")
    role = str(request_data.get("recipient_role") or "").upper()
    action = str(request_data.get("action") or "").upper()
    if role not in ROLES:raise ValueError("Choose a recipient role.")
    if action not in ACTIONS:raise ValueError("Choose document, information, signature request, or approval.")
    document_id=request_data.get("document_id") or None
    if document_id:
        if not PMPropertyDocument.objects.filter(
            workspace=workspace,property=prop,pk=document_id).exists():
            raise ValueError("Attached document must belong to this property.")
        document_id=int(document_id)
    title=_string(request_data.get("title") or "",180)
    if len(title)<4:raise ValueError("Describe what document or action is required.")
    description=_string(request_data.get("instructions") or "",1800)
    due=_iso(request_data.get("due_date") or "")
    today=timezone.localdate()
    if due and date.fromisoformat(due)<today:
        raise ValueError("The due date must not be in the past.")
    return {
        "property_id":prop.id,"title":title,"instructions":description,
        "recipient_role":role,"recipient_name":_string(request_data.get("recipient_name") or "",140),
        "recipient_email":_valid_mail(request_data.get("recipient_email")),
        "action":action,"status":"DRAFT","due_date":due,"document_id":document_id,
        "sent_at":"","last_reminder_at":"","next_followup_date":"",
        "completion_evidence":"","completion_document_id":None,
        "approved_signature_method":_string(request_data.get("approved_signature_method") or "",120),
        "history":[{"event":"CREATED","when":timezone.now().isoformat(),"by":request_data.get("_actor")}],
    }

def _send_email(workspace, prop, fields, reminder=False):
    # No untrusted URLs, tokens, PDFs, tax IDs, or sensitive excerpts included.
    action_word = {
        "PROVIDE_DOCUMENT":"provide a document",
        "PROVIDE_INFORMATION":"provide information",
        "SIGNATURE":"coordinate a signature",
        "APPROVAL":"review an approval request",
    }.get(fields["action"],"respond to a request")
    subject=f"{workspace.name}: action requested — {fields['title']}"
    body=(
        f"Hello {fields.get('recipient_name') or 'there'},\n\n"
        f"{workspace.name} requests that you {action_word}.\n"
        f"Request: {fields['title']}\n"
        f"Property: {prop.name}\n"
        f"Details: {fields.get('instructions') or 'Please contact the sender for instructions.'}\n"
        f"Requested by: {fields.get('due_date') or 'Please respond when possible'}\n\n"
        "Please reply to this email or use the official submission or secure signing "
        "channel your organization accepts. Do not email sensitive identity, tax or "
        "banking records as ordinary attachments.\n\n"
        "Important: This email is NOT an electronic-signature link and does not indicate "
        "that any housing authority has received, accepted or approved a document.\n\n"
        f"{workspace.sender_name or workspace.name}\n"
    )
    reply=workspace.reply_to_email or workspace.office_email or ""
    if reply:
        try:validate_email(reply)
        except DjangoValidationError:reply=""
    email=EmailMultiAlternatives(
        subject=subject,body=body,
        from_email=getattr(settings,"DEFAULT_FROM_EMAIL","notifications@syncworksapp.com"),
        to=[fields["recipient_email"]],reply_to=[reply] if reply else None)
    if email.send(fail_silently=False) != 1:
        raise RuntimeError("No outbound message accepted by email service.")

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def document_requests(request,property_id):
    workspace,prop=_property(request,property_id)
    if not prop:return Response({"detail":"Property not found in this portfolio."},status=404)
    if request.method=="GET":
        packets=PMDocumentPacket.objects.filter(workspace=workspace,packet_type=TYPE,
                          field_data__property_id=prop.id).order_by("-updated_at")[:250]
        today=timezone.localdate().isoformat()
        rows=[]
        for packet in packets:
            entry=_serialize(packet)
            entry["overdue"]=bool(entry.get("due_date") and entry["due_date"]<today and entry["status"] not in CLOSED)
            entry["followup_due"]=bool(entry.get("next_followup_date") and
                                       entry["next_followup_date"]<=today and entry["status"] not in CLOSED)
            rows.append(entry)
        return Response({"requests":rows,"count":len(rows),
            "notice":"Status is reported/verified by the manager; email delivery does not prove external agency approval or legal signature."})
    with transaction.atomic():
        try:
            data={**request.data,"_actor":request.user.pk}
            fields=_draft(data,workspace,prop)
        except ValueError as exc:return Response({"detail":str(exc)},status=400)
        packet=PMDocumentPacket.objects.create(
            workspace=workspace,packet_type=TYPE,state_code=prop.state,
            template_name="External document / signature coordination",
            field_data=fields)
    return Response({"request":_serialize(packet)},status=201)

@api_view(["POST","PATCH"])
@permission_classes([IsAuthenticated])
def document_request_detail(request,property_id,request_id):
    workspace,prop=_property(request,property_id)
    if not prop:return Response({"detail":"Property not found."},status=404)
    with transaction.atomic():
        packet=_get_request(workspace,prop,request_id)
        if not packet:return Response({"detail":"Request not found."},status=404)
        data=dict(packet.field_data)
        now=timezone.now()
        if request.method=="POST":
            op=str(request.data.get("operation") or "").upper()
            if op not in {"SEND","REMIND"}:
                return Response({"detail":"Choose SEND or REMIND explicitly."},status=400)
            if data.get("status") in CLOSED:
                return Response({"detail":"Closed requests cannot be sent."},status=409)
            last=(data.get("last_reminder_at") or data.get("sent_at")) if op=="REMIND" else data.get("sent_at")
            if op=="REMIND" and not data.get("sent_at"):
                return Response({"detail":"Send the original request before a reminder."},status=409)
            if last:
                try:
                    from datetime import datetime
                    sent=datetime.fromisoformat(last)
                    if (now-sent).total_seconds()<24*3600:
                        return Response({"detail":"Wait at least 24 hours before sending another email."},status=429)
                except (TypeError,ValueError):
                    pass
            try:_send_email(workspace,prop,data,reminder=(op=="REMIND"))
            except Exception:
                return Response({"detail":"Email delivery failed. The request remains pending; verify mail configuration."},status=502)
            if op=="SEND":
                data["sent_at"]=now.isoformat()
                data["status"]="SENT"
            else:
                data["last_reminder_at"]=now.isoformat()
            data["next_followup_date"]=str(timezone.localdate()+timedelta(days=3))
            data.setdefault("history",[]).append({"event":op,"when":now.isoformat(),"by":request.user.pk})
            packet.field_data=data;packet.status=PMDocumentPacket.Status.SENT
            packet.save(update_fields=["field_data","status","updated_at"])
            return Response({"request":_serialize(packet),"detail":"Email sent; no external signature or approval has been recorded."})
        next_state=str(request.data.get("status") or "").upper()
        if next_state not in STATES or next_state=="SENT":
            return Response({"detail":"Invalid status. Sending is a separate verified action."},status=400)
        if data.get("status")=="DRAFT" and next_state not in {"DRAFT","CANCELED"}:
            return Response({"detail":"Send the request before advancing its response status."},status=409)
        evidence=_string(request.data.get("completion_evidence") or "",1300)
        doc_id=request.data.get("completion_document_id") or None
        if doc_id and not PMPropertyDocument.objects.filter(
            workspace=workspace,property=prop,pk=doc_id).exists():
            return Response({"detail":"The evidence document must belong to this property."},status=400)
        if next_state in {"RECEIVED","VERIFIED"} and not (evidence or doc_id):
            return Response({"detail":"Record a receipt reference, reply evidence, or uploaded document first."},status=400)
        if next_state=="VERIFIED" and data.get("action")=="SIGNATURE":
            if not (doc_id and evidence):
                return Response({"detail":"Signature verification requires the signed document and method/source note."},status=400)
        if next_state=="VERIFIED" and data.get("action")=="APPROVAL":
            if not (doc_id and evidence):
                return Response({"detail":"Agency approval requires an approval document and confirmation source."},status=400)
        data["status"]=next_state
        data["completion_evidence"]=evidence
        data["completion_document_id"]=int(doc_id) if doc_id else None
        data["next_followup_date"]="" if next_state in CLOSED else data.get("next_followup_date","")
        data.setdefault("history",[]).append({"event":"STATUS_"+next_state,"when":now.isoformat(),
             "by":request.user.pk,"evidence":evidence[:180]})
        packet.field_data=data
        packet.save(update_fields=["field_data","updated_at"])
        return Response({"request":_serialize(packet)})
        
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def analyze_document_correspondence(request,property_id):
    workspace,prop=_property(request,property_id)
    if not prop:return Response({"detail":"Property not found."},status=404)
    body=request.data.get("body")
    if not isinstance(body,str) or len(body)>12000:
        return Response({"detail":"Paste an email excerpt under 12,000 characters."},status=400)
    lower=body.lower()
    suggestions=[]
    for key,phrases in DOC_KEYWORDS.items():
        match=next((p for p in phrases if p in lower),None)
        if match:
            at=lower.find(match)
            excerpt=re.sub(r"\s+"," ",body[max(0,at-85):min(len(body),at+len(match)+115)]).strip()
            suggestions.append({"checklist_key":key,"matched_phrase":match,
                                "source_excerpt":excerpt,"confidence":"KEYWORD_MATCH",
                                "action":"Review the source and choose whether to request, attach or mark this item received."})
    return Response({"suggestions":suggestions,"stored":False,
        "notice":"Keyword-based suggestions, not an AI determination or proof an agency requires these forms. No email or checklist was modified."})
