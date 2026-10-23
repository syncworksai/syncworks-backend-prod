"""Property handoff case: document-led, provider-agnostic transfer onboarding.

This is intentionally separate from live rent/tenant ledger entries.
Case steps and opening balances are evidence records, NOT charges or receipts.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace
from .document_models import PMPropertyDocument
from .models import PMDocumentPacket, PMProperty

PACKET_TYPE = "PROPERTY_HANDOFF"
CASE_KINDS = {"NEW_MANAGEMENT", "SELF_MANAGE", "PURCHASE", "INITIAL_SETUP", "OTHER"}
ASSISTANCE_TYPES = {"NONE", "HOUSING_VOUCHER", "OTHER_ASSISTANCE"}
RENTAL_CHANNELS = {"DIRECT", "FURNISHED_FINDER", "CORPORATE", "OTHER"}
MANAGEMENT_MODELS = {"OWNER_MANAGED", "THIRD_PARTY_MANAGER"}
TASK_STATUSES = {"NOT_STARTED", "REQUESTED", "RECEIVED", "VERIFIED", "NOT_APPLICABLE"}
MONEY_STATES = {"UNKNOWN", "REPORTED", "DOCUMENTED", "DISPUTED", "RECONCILED"}
CASE_STATUSES = {"IN_PROGRESS", "AWAITING_DOCUMENTS", "AWAITING_APPROVAL", "READY_TO_REVIEW", "COMPLETED"}

GENERAL_TASKS = [
    {"key":"ownership_authority", "title":"Proof of ownership or management authority", "why":"Establish who owns the property and who may act for the owner", "required":True},
    {"key":"transition_agreement", "title":"Prior manager termination / transfer authorization", "why":"Identify the effective date and permitted handoff", "required":True},
    {"key":"current_lease", "title":"Existing lease, addenda and rent schedule", "why":"Preserve tenant obligations and applicable late-fee rules", "required":True},
    {"key":"tenant_notice", "title":"Notice to residents with new contact and payment instructions", "why":"Prevent rent being paid to the wrong recipient", "required":True},
    {"key":"rent_ledger", "title":"Tenant and owner ledgers with dated receipts", "why":"Reconcile arrears, credits, fees and owner distributions", "required":True},
    {"key":"deposit_accounting", "title":"Security deposits and escrow transfer accounting", "why":"Separate tenant-held funds from income and document custody", "required":True},
    {"key":"open_work", "title":"Open repairs, inspections, keys and warranties", "why":"Transfer work orders and prevent missed safety issues", "required":True},
    {"key":"insurance_tax", "title":"Insurance, tax and contact records", "why":"Keep owner and vendor records available", "required":False},
]
FURNISHED_TASKS = [
    {"key":"furnished_inventory","title":"Furnished unit inventory and condition photos","why":"Document furnishings and responsibility for any damage","required":True},
    {"key":"midterm_lease","title":"Mid-term rental lease, utilities and term","why":"Use state-appropriate terms and confirm booking terms, not a short-stay template","required":True},
    {"key":"movein_arrival","title":"Move-in instructions and access verification","why":"Document arrival, keys, parking and emergency contact","required":False},
]
ASSISTANCE_TASKS = [
    {"key":"provider_packet", "title":"Local assistance administrator's change packet", "why":"Obtain the administrator-specific forms; requirements vary by jurisdiction", "required":True},
    {"key":"provider_owner_docs", "title":"Ownership / agency proof and tax or direct-deposit forms", "why":"Submit only the documents required by the specific administrator", "required":True},
    {"key":"provider_contract", "title":"Assistance contract, assignment and rent determination", "why":"Record legal payee, effective date and monthly payer split", "required":True},
    {"key":"provider_approval", "title":"Administrator approval and vendor/payee confirmation", "why":"Do not presume payee information changes on notice alone", "required":True},
    {"key":"provider_inspection", "title":"Inspection history, outstanding deficiencies and deadlines", "why":"Protect compliance and avoid missed inspections", "required":True},
    {"key":"provider_payment", "title":"Assistance payment history and outstanding funds", "why":"Separate payments to former manager from money held or paid to you", "required":True},
]

def tasks_for(assistance_type, rental_channel="DIRECT"):
    return GENERAL_TASKS + (FURNISHED_TASKS if rental_channel == "FURNISHED_FINDER" else []) + (ASSISTANCE_TASKS if assistance_type != "NONE" else [])

def defaults():
    return {
        "case_kind": "NEW_MANAGEMENT", "status": "IN_PROGRESS",
        "rental_channel": "DIRECT", "management_model": "OWNER_MANAGED",
        "effective_date": "", "former_manager": {"name":"", "email":"", "phone":"", "notice_sent_date":""},
        "assistance": {"type":"NONE", "administrator":"", "administrator_website":"", "contact_email":"",
                       "contract_status":"UNKNOWN", "payee_status":"UNKNOWN"},
        "tasks": {}, "opening_balances": [], "notes":"",
    }

def scope(request, property_id):
    workspace = _workspace(request)
    obj = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    return workspace, obj

def _packet(workspace, property_id, create=False):
    p = PMDocumentPacket.objects.filter(
        workspace=workspace, packet_type=PACKET_TYPE, field_data__property_id=property_id
    ).order_by("-id").first()
    if p or not create:
        return p
    fields = defaults()
    fields["property_id"] = property_id
    return PMDocumentPacket.objects.create(
        workspace=workspace, packet_type=PACKET_TYPE, field_data=fields,
        template_name="Property onboarding / handoff", template_version="1",
    )

def _valid_iso(value):
    if not value:
        return ""
    try:
        value = str(value)
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return value
    except ValueError:
        raise ValueError("Dates must be YYYY-MM-DD.")

def _text(value, limit=500):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Provide a valid text field.")
    return value.strip()

def _money_record(item):
    if not isinstance(item, dict):
        raise ValueError("Opening-balance records must be objects.")
    kind = str(item.get("type") or "").upper()
    if kind not in {"TENANT_AR", "ASSISTANCE_AR", "FORMER_MANAGER_FUNDS", "SECURITY_DEPOSIT",
                    "PREPAID_RENT", "REPAIR_ADVANCE", "OTHER"}:
        raise ValueError("Unknown opening-balance type.")
    try:
        amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Opening balances must be valid amounts.")
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999.99"):
        raise ValueError("Opening balances must be nonnegative and finite.")
    evidence = str(item.get("evidence_status") or "UNKNOWN").upper()
    if evidence not in MONEY_STATES:
        raise ValueError("Invalid balance evidence status.")
    return {"id": _text(item.get("id") or "", 100), "type": kind, "amount": str(amount),
            "evidence_status": evidence, "period": _text(item.get("period") or "", 30),
            "counterparty": _text(item.get("counterparty") or "", 150),
            "source_note": _text(item.get("source_note") or "", 1000)}

def _validate(workspace, property_id, prior, updates):
    if not isinstance(updates, dict):
        raise ValueError("Invalid handoff data.")
    allowed = {"case_kind", "status", "effective_date", "former_manager", "assistance", "tasks",
               "opening_balances", "notes", "rental_channel", "management_model"}
    if set(updates) - allowed:
        raise ValueError("Unsupported handoff field.")
    data = {**prior, "property_id": property_id}
    if "case_kind" in updates:
        kind = str(updates["case_kind"]).upper()
        if kind not in CASE_KINDS: raise ValueError("Invalid setup type.")
        data["case_kind"] = kind
    if "status" in updates:
        case_status = str(updates["status"]).upper()
        if case_status not in CASE_STATUSES: raise ValueError("Invalid case status.")
        data["status"] = case_status
    if "rental_channel" in updates:
        channel = str(updates["rental_channel"]).upper()
        if channel not in RENTAL_CHANNELS: raise ValueError("Invalid rental channel.")
        data["rental_channel"] = channel
    if "management_model" in updates:
        model = str(updates["management_model"]).upper()
        if model not in MANAGEMENT_MODELS: raise ValueError("Invalid management model.")
        data["management_model"] = model
    if "effective_date" in updates:
        data["effective_date"] = _valid_iso(updates["effective_date"])
    if "notes" in updates:
        data["notes"] = _text(updates["notes"], 4000)
    if "former_manager" in updates:
        p = updates["former_manager"]
        if not isinstance(p, dict): raise ValueError("Invalid prior-manager details.")
        data["former_manager"] = {
            "name": _text(p.get("name") or "", 180), "email": _text(p.get("email") or "", 250),
            "phone": _text(p.get("phone") or "", 80),
            "notice_sent_date": _valid_iso(p.get("notice_sent_date") or ""),
        }
    if "assistance" in updates:
        a = updates["assistance"]
        if not isinstance(a, dict): raise ValueError("Invalid assistance details.")
        kind = str(a.get("type") or "NONE").upper()
        if kind not in ASSISTANCE_TYPES: raise ValueError("Invalid assistance type.")
        data["assistance"] = {
            "type": kind, "administrator": _text(a.get("administrator") or "", 180),
            "administrator_website": _text(a.get("administrator_website") or "", 500),
            "contact_email": _text(a.get("contact_email") or "", 250),
            "contract_status": _text(a.get("contract_status") or "UNKNOWN", 80),
            "payee_status": _text(a.get("payee_status") or "UNKNOWN", 80),
        }
    if "tasks" in updates:
        raw = updates["tasks"]
        if not isinstance(raw, dict): raise ValueError("Invalid checklist.")
        allowed_tasks = {task["key"] for task in GENERAL_TASKS + ASSISTANCE_TASKS + FURNISHED_TASKS}
        if set(raw) - allowed_tasks: raise ValueError("Unsupported checklist task.")
        result = dict(data.get("tasks") or {})
        for key, value in raw.items():
            if not isinstance(value, dict): raise ValueError("Invalid checklist item.")
            state = str(value.get("status") or "NOT_STARTED").upper()
            if state not in TASK_STATUSES: raise ValueError("Invalid checklist status.")
            note = _text(value.get("note") or "", 1000)
            doc_id = value.get("document_id") or None
            if doc_id:
                if not PMPropertyDocument.objects.filter(pk=doc_id, workspace=workspace, property_id=property_id).exists():
                    raise ValueError("Referenced document must belong to this property and portfolio.")
                doc_id = int(doc_id)
            if state == "VERIFIED" and not (note or doc_id):
                raise ValueError("Verified checklist steps need a document or source note.")
            if state == "NOT_APPLICABLE" and not note:
                raise ValueError("Marking a task not applicable requires an explanation.")
            result[key] = {"status": state, "note": note, "document_id": doc_id,
                           "updated_at": timezone.now().isoformat()}
        data["tasks"] = result
    if "opening_balances" in updates:
        raw = updates["opening_balances"]
        if not isinstance(raw, list) or len(raw) > 100:
            raise ValueError("Provide no more than 100 opening balances.")
        data["opening_balances"] = [_money_record(item) for item in raw]
    if data.get("status") == "COMPLETED":
        mandatory = [t["key"] for t in tasks_for(data.get("assistance", {}).get("type", "NONE"), data.get("rental_channel", "DIRECT"))
                     if t["required"]]
        if any((data.get("tasks", {}).get(key) or {}).get("status") not in {"VERIFIED", "NOT_APPLICABLE"} for key in mandatory):
            raise ValueError("Complete or mark each required step not applicable before closing the handoff.")
        if any(r["evidence_status"] in {"UNKNOWN", "REPORTED", "DISPUTED"} for r in data.get("opening_balances") or []):
            raise ValueError("Reconcile or document all opening balances before closing the handoff.")
    return data

@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def property_handoff(request, property_id):
    workspace, property_obj = scope(request, property_id)
    if not property_obj:
        return Response({"detail":"Property not found in this portfolio."}, status=status.HTTP_404_NOT_FOUND)
    packet = _packet(workspace, property_obj.id, create=request.method == "PATCH")
    data = ({**defaults(), **(packet.field_data or {})} if packet else {**defaults(), "property_id": property_obj.id})
    if request.method == "PATCH":
        try:
            data = _validate(workspace, property_obj.id, data, request.data)
        except ValueError as exc:
            return Response({"detail":str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        packet.field_data = data
        packet.save(update_fields=["field_data", "updated_at"])
    tasks = tasks_for(data.get("assistance", {}).get("type", "NONE"))
    for task in tasks:
        task["state"] = (data.get("tasks", {}).get(task["key"]) or {}).get("status", "NOT_STARTED")
    completed = sum(1 for task in tasks if task["state"] in {"VERIFIED", "NOT_APPLICABLE"})
    return Response({
        "property": {"id": property_obj.id, "name": property_obj.name, "address": property_obj.address,
                     "city": property_obj.city, "state": property_obj.state},
        "handoff": data, "checklist": tasks,
        "progress": {"completed": completed, "total": len(tasks)},
        "notice": "A handoff record is not confirmation of agency approval, payment receipt, legal sufficiency or ledger settlement.",
    })
