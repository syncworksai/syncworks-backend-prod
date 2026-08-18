from __future__ import annotations

import re
from datetime import datetime, timezone as dt_timezone

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.dateparse import parse_datetime

from pm_workspace.communication_models import PMConversation, PMConversationMessage
from pm_workspace.lead_models import PMLead, PMLeadMessage
from pm_workspace.models import PMProperty, PMTenant, PMWorkspace
from pm_workspace.owner_models import PMPropertyOwner


LEAD_DOMAINS = {
    "furnishedfinder.com": PMLead.Source.FURNISHED_FINDER,
    "leads.furnishedfinder.com": PMLead.Source.FURNISHED_FINDER,
    "zillow.com": PMLead.Source.ZILLOW,
    "apartments.com": PMLead.Source.APARTMENTS,
}
FINANCE_HINTS = ("usaa", "credit card", "bank account", "statement available", "payment due", "transaction alert", "brokerage")
LEAD_HINTS = ("interested in your property", "traveler message", "new lead", "rental inquiry", "property inquiry", "booking inquiry", "availability inquiry")
MAINTENANCE_HINTS = ("maintenance", "repair", "leak", "air conditioner", "a/c", "ac not", "no heat", "plumbing", "toilet", "broken", "work order")
COLLECTIONS_HINTS = ("collections", "eviction", "money judgment", "law firm", "attorney", "court", "demand letter")
SECTION8_HINTS = ("section 8", "housing authority", "hap", "voucher", "hud", "rent increase request")
CORPORATE_HINTS = ("corporate housing", "corporate leasing", "relocation specialist", "company housing", "client very interested")
INSURANCE_HINTS = ("insurance housing", "insurance carrier", "adjuster", "claim number", "displacement housing", "temporary housing claim")


def _email_address(remote):
    return str((((remote.get("from") or {}).get("emailAddress") or {}).get("address")) or "").strip().lower()


def _sender_name(remote):
    return str((((remote.get("from") or {}).get("emailAddress") or {}).get("name")) or "").strip()


def _body(remote):
    content = str(((remote.get("body") or {}).get("content")) or remote.get("bodyPreview") or "")
    return re.sub(r"\s+", " ", strip_tags(content)).strip()


def _received_at(remote):
    value = parse_datetime(str(remote.get("receivedDateTime") or ""))
    if not value:
        return timezone.now()
    return value if timezone.is_aware(value) else timezone.make_aware(value, dt_timezone.utc)


def _domain(email):
    return email.split("@", 1)[-1].lower() if "@" in email else ""


def _source(sender_email, subject, text):
    domain = _domain(sender_email)
    for key, source in LEAD_DOMAINS.items():
        if domain == key or domain.endswith("." + key):
            return source
    lower = f"{subject} {text}".lower()
    if "furnished finder" in lower:
        return PMLead.Source.FURNISHED_FINDER
    if "zillow" in lower:
        return PMLead.Source.ZILLOW
    if "apartments.com" in lower:
        return PMLead.Source.APARTMENTS
    if "facebook" in lower:
        return PMLead.Source.FACEBOOK
    if "instagram" in lower:
        return PMLead.Source.INSTAGRAM
    return PMLead.Source.OTHER


def _lead_type(subject, text):
    lower = f"{subject} {text}".lower()
    if any(term in lower for term in INSURANCE_HINTS):
        return PMLead.LeadType.INSURANCE
    if any(term in lower for term in CORPORATE_HINTS):
        return PMLead.LeadType.CORPORATE
    if any(term in lower for term in SECTION8_HINTS):
        return PMLead.LeadType.SECTION8
    if "relocation" in lower:
        return PMLead.LeadType.RELOCATION
    return PMLead.LeadType.REGULAR


def _property_match(workspace, subject, text):
    haystack = f"{subject} {text}".lower()
    for prop in PMProperty.objects.filter(workspace=workspace).order_by("id"):
        for token in (prop.name, prop.address):
            if token and str(token).lower() in haystack:
                return prop
    return None


def _parse_name(subject, sender_name):
    match = re.search(r"direct message from\s+(.+?)\s+for\s+", subject, flags=re.I)
    full = (match.group(1).strip() if match else sender_name).strip()
    parts = full.split(None, 1)
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def classify_for_workspace(workspace, sender_email, subject, text):
    lower = f"{subject} {text} {sender_email}".lower()
    tenant = PMTenant.objects.filter(workspace=workspace, email__iexact=sender_email).first() if sender_email else None
    owner = PMPropertyOwner.objects.filter(workspace=workspace, email__iexact=sender_email).first() if sender_email else None
    if tenant:
        if any(term in lower for term in MAINTENANCE_HINTS):
            return {"kind": "PM_MESSAGE", "category": PMConversation.Category.MAINTENANCE, "tenant": tenant, "confidence": 98, "reason": "Known tenant + maintenance language"}
        return {"kind": "PM_MESSAGE", "category": PMConversation.Category.TENANT, "tenant": tenant, "confidence": 99, "reason": "Known tenant email"}
    if owner:
        return {"kind": "PM_MESSAGE", "category": PMConversation.Category.INVESTOR, "owner": owner, "confidence": 99, "reason": "Known owner/investor email"}
    if any(term in lower for term in COLLECTIONS_HINTS):
        return {"kind": "PM_MESSAGE", "category": PMConversation.Category.COLLECTIONS, "confidence": 90, "reason": "Collections/legal language"}
    source = _source(sender_email, subject, text)
    if source != PMLead.Source.OTHER or any(term in lower for term in LEAD_HINTS):
        return {"kind": "LEAD", "source": source, "lead_type": _lead_type(subject, text), "confidence": 94 if source != PMLead.Source.OTHER else 82, "reason": "Rental lead source or inquiry language"}
    if any(term in lower for term in SECTION8_HINTS):
        return {"kind": "PM_MESSAGE", "category": PMConversation.Category.INTERNAL, "confidence": 86, "reason": "Housing authority / Section 8 language"}
    if any(term in lower for term in MAINTENANCE_HINTS):
        return {"kind": "PM_MESSAGE", "category": PMConversation.Category.MAINTENANCE, "confidence": 72, "reason": "Maintenance language"}
    if any(term in lower for term in FINANCE_HINTS):
        return {"kind": "FINANCE", "confidence": 92, "reason": "Personal finance/banking language"}
    return {"kind": "IGNORE", "confidence": 55, "reason": "No PM work signal found"}


def _upsert_lead(user, connection, workspace, remote, sender_email, sender_name, subject, text, classification):
    thread_id = str(remote.get("conversationId") or "")
    external_id = str(remote.get("id") or "")
    lead = None
    if thread_id:
        lead = PMLead.objects.filter(workspace=workspace, external_thread_id=thread_id).first()
    if not lead and sender_email:
        lead = PMLead.objects.filter(workspace=workspace, email__iexact=sender_email).exclude(stage__in=[PMLead.Stage.WON, PMLead.Stage.LOST]).order_by("-updated_at").first()
    first, last = _parse_name(subject, sender_name)
    prop = _property_match(workspace, subject, text)
    if not lead:
        lead = PMLead.objects.create(
            workspace=workspace,
            property=prop,
            stage=PMLead.Stage.NEW,
            lead_type=classification.get("lead_type") or PMLead.LeadType.REGULAR,
            source=classification.get("source") or PMLead.Source.OTHER,
            source_label=PMLead.Source(classification.get("source") or PMLead.Source.OTHER).label,
            first_name=first,
            last_name=last,
            email=sender_email,
            summary=text[:2000],
            classification_confidence=classification.get("confidence") or 0,
            classification_reason=classification.get("reason") or "",
            mailbox_connection_id=connection.get("id") or "",
            external_thread_id=thread_id,
            source_subject=subject[:255],
            metadata={"provider": connection.get("provider"), "mailbox": connection.get("email"), "web_link": remote.get("webLink") or ""},
            created_by=user,
        )
    else:
        changed = False
        if prop and not lead.property_id:
            lead.property = prop; changed = True
        if thread_id and not lead.external_thread_id:
            lead.external_thread_id = thread_id; changed = True
        if not lead.mailbox_connection_id:
            lead.mailbox_connection_id = connection.get("id") or ""; changed = True
        if changed:
            lead.save()
    PMLeadMessage.objects.get_or_create(
        lead=lead,
        external_message_id=external_id,
        defaults={
            "direction": PMLeadMessage.Direction.INBOUND,
            "channel": PMLeadMessage.Channel.EMAIL,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "recipient_email": connection.get("email") or "",
            "subject": subject[:255],
            "body": text,
            "external_thread_id": thread_id,
            "mailbox_connection_id": connection.get("id") or "",
            "sent_at": _received_at(remote),
        },
    )
    return lead


def _upsert_pm_message(user, workspace, remote, sender_email, sender_name, subject, text, classification):
    tenant = classification.get("tenant")
    owner = classification.get("owner")
    prop = _property_match(workspace, subject, text)
    if tenant and not prop:
        prop = PMProperty.objects.filter(workspace=workspace, name__iexact=tenant.property_name).first()
    conversation = PMConversation.objects.filter(workspace=workspace, requester_email__iexact=sender_email, subject=subject[:220], status__in=[PMConversation.Status.OPEN, PMConversation.Status.WAITING_PM, PMConversation.Status.WAITING_REQUESTER]).first()
    if not conversation:
        prefix = "Section 8 · " if "Section 8" in classification.get("reason", "") else ""
        conversation = PMConversation.objects.create(
            workspace=workspace,
            category=classification.get("category") or PMConversation.Category.INTERNAL,
            status=PMConversation.Status.WAITING_PM,
            subject=(prefix + subject)[:220] or "External email",
            tenant=tenant,
            property=prop,
            property_owner=owner,
            requester_name=sender_name,
            requester_email=sender_email,
            internal_only=False,
            created_by=user,
        )
    if not conversation.messages.filter(body=text).exists():
        PMConversationMessage.objects.create(conversation=conversation, sender_role=PMConversationMessage.SenderRole.SYSTEM, body=text)
    if conversation.status != PMConversation.Status.WAITING_PM:
        conversation.status = PMConversation.Status.WAITING_PM
        conversation.save(update_fields=["status", "updated_at"])
    return conversation


@transaction.atomic
def import_microsoft_mail(user, connection, access_token):
    if not connection.get("mail_enabled"):
        return {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}
    destinations = {str(v).upper() for v in connection.get("mail_destinations") or []}
    workspace_ids = [int(v) for v in connection.get("pm_workspace_ids") or [] if str(v).isdigit()]
    if "PM" not in destinations or not workspace_ids:
        return {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}
    workspaces = list(PMWorkspace.objects.filter(owner=user, is_active=True, id__in=workspace_ids))
    if not workspaces:
        return {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}

    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "$top": 50,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,webLink",
        },
        timeout=45,
    )
    response.raise_for_status()
    last_sync = parse_datetime(str(connection.get("mail_last_synced_at") or "")) if connection.get("mail_last_synced_at") else None
    if last_sync and timezone.is_naive(last_sync):
        last_sync = timezone.make_aware(last_sync, dt_timezone.utc)
    counts = {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}
    for remote in reversed(response.json().get("value") or []):
        received = _received_at(remote)
        if last_sync and received <= last_sync:
            continue
        sender_email = _email_address(remote)
        if sender_email and sender_email == str(connection.get("email") or "").lower():
            continue
        sender_name = _sender_name(remote)
        subject = str(remote.get("subject") or "").strip()
        text = _body(remote)
        counts["processed"] += 1
        routed = False
        for workspace in workspaces:
            classification = classify_for_workspace(workspace, sender_email, subject, text)
            if classification["kind"] == "LEAD" and "LEADS" in {str(v).upper() for v in connection.get("mail_categories") or []}:
                _upsert_lead(user, connection, workspace, remote, sender_email, sender_name, subject, text, classification)
                counts["leads"] += 1; routed = True
                break
            if classification["kind"] == "PM_MESSAGE":
                _upsert_pm_message(user, workspace, remote, sender_email, sender_name, subject, text, classification)
                counts["pm_messages"] += 1; routed = True
                break
        if not routed:
            counts["ignored"] += 1
    return counts


def send_microsoft_mail(access_token, *, to_email, subject, body):
    response = requests.post(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
            },
            "saveToSentItems": True,
        },
        timeout=30,
    )
    if response.status_code not in {200, 202}:
        response.raise_for_status()
    return True
