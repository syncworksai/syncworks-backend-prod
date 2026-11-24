"""Property-scoped historical Outlook correspondence search.

Searches a bounded window across mail folders, without filing or sending.
Property profiles are owner-scoped and account-scoped. No provider-specific
names are required: terms and contacts are supplied by the property manager.
"""
import logging
import re
from collections import Counter
from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse, quote
from pm_workspace.models import PMProperty

import requests
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .assist_multi_mailbox_views import settings, snapshot, graph, access_token, GRAPH
from .assist_property_mail_analysis import classify

logger = logging.getLogger(__name__)
PROFILE = "sync_assist.property.search_profile"
REPORT = "sync_assist.property.correspondence_report"
MAX_PROFILES = 500
MAX_TERMS = 15
MAX_MESSAGES = 300


def profiles(user, mailbox):
    results = {}
    for event in AuditLog.objects.filter(actor=user, action=PROFILE).order_by("id"):
        item = event.metadata or {}
        if item.get("mailbox_id") != mailbox:
            continue
        identifier = item.get("profile_id")
        if identifier:
            results[identifier] = dict(item)
    return list(results.values())


def property_for_user(user, property_id):
    if not str(property_id or "").isdigit():
        return None
    return PMProperty.objects.filter(pk=property_id, workspace__owner=user,
                                     workspace__is_active=True).first()


def matches(message, profile):
    subject = str(message.get("subject") or "")[:500].lower()
    body = str(message.get("bodyPreview") or "")[:1000].lower()
    sender = str(((message.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
    context = subject + " " + body
    matched = []
    for term in profile["terms"]:
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", context):
            matched.append(term)
    for contact in profile["contacts"]:
        if sender == contact.lower():
            matched.append("contact:" + contact)
    return matched


def mailbox(request, account_id):
    if not _pilot(request.user):
        return None
    return next((a for a in snapshot(request.user)
                 if a["account_id"] == str(account_id) and a["category"] == "PROPERTY"), None)


class PropertySearchProfilesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        if not mailbox(request, account_id):
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        owned = PMProperty.objects.filter(workspace__owner=request.user,
                                          workspace__is_active=True).order_by("name", "id")[:250]
        return Response({"profiles": profiles(request.user, str(account_id)),
                         "pm_properties": [
                             {"id": p.id, "name": p.name,
                              "address": ", ".join(filter(None, [p.address, p.city, p.state, p.zip]))}
                             for p in owned
                         ], "max_profiles": MAX_PROFILES, "mode": "READ_ONLY_SEARCH"})

    def post(self, request, account_id):
        if not mailbox(request, account_id):
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        existing = profiles(request.user, str(account_id))
        if len(existing) >= MAX_PROFILES:
            return Response({"detail": "Maximum property search profiles reached."}, status=400)
        name = str(request.data.get("name") or "").strip()
        raw_terms = request.data.get("terms")
        raw_contacts = request.data.get("contacts", [])
        if not isinstance(raw_terms, list) or not isinstance(raw_contacts, list):
            return Response({"detail": "Search terms and contacts must be lists."}, status=400)
        if not 2 <= len(name) <= 80 or not raw_terms or len(raw_terms) > MAX_TERMS or len(raw_contacts) > 12:
            return Response({"detail": "Provide a property name and 1–15 search terms, with up to 12 contacts."}, status=400)
        if any(not isinstance(x, str) or not 2 <= len(x.strip()) <= 100 for x in raw_terms + raw_contacts):
            return Response({"detail": "Each term or contact must be 2–100 characters."}, status=400)
        terms = list(dict.fromkeys(x.strip().lower() for x in raw_terms))
        contacts = list(dict.fromkeys(x.strip().lower() for x in raw_contacts))
        if any("@" not in x or " " in x for x in contacts):
            return Response({"detail": "Contacts must be complete email addresses."}, status=400)
        pm_id = request.data.get("pm_property_id")
        pm_property = property_for_user(request.user, pm_id) if pm_id else None
        if pm_id and not pm_property:
            return Response({"detail": "Choose a Property Management property you own."}, status=403)
        if pm_property and any(x.get("pm_property_id") == pm_property.id for x in existing):
            return Response({"detail": "Property already linked to a search profile."}, status=409)
        profile = {"profile_id": str(uuid4()), "mailbox_id": str(account_id),
                   "name": pm_property.name if pm_property else name,
                   "terms": terms, "contacts": contacts,
                   "pm_property_id": pm_property.id if pm_property else None,
                   "property_address": pm_property.address if pm_property else ""}
        AuditLog.objects.create(actor=request.user, action=PROFILE, metadata=profile)
        return Response({"profile": profile, "notice": "Search profile saved. No Outlook mail was changed."}, status=201)

    def patch(self, request, account_id):
        if not mailbox(request, account_id):
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        prior = next((p for p in profiles(request.user, str(account_id))
                      if p["profile_id"] == str(request.data.get("profile_id") or "")), None)
        pm_property = property_for_user(request.user, request.data.get("pm_property_id"))
        if not prior or not pm_property:
            return Response({"detail": "Saved search or authorized property not found."}, status=404)
        if any(x.get("profile_id") != prior["profile_id"]
               and x.get("pm_property_id") == pm_property.id
               for x in profiles(request.user, str(account_id))):
            return Response({"detail": "Property already linked to another profile."}, status=409)
        prior.update({"name": pm_property.name, "pm_property_id": pm_property.id,
                      "property_address": pm_property.address})
        AuditLog.objects.create(actor=request.user, action=PROFILE, metadata=prior)
        return Response({"profile": prior, "notice": "Linked to Property Management; no mail changed."})


class PropertyHistoricalSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, account_id):
        account = mailbox(request, account_id)
        if not account:
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        profile = next((x for x in profiles(request.user, str(account_id))
                        if x["profile_id"] == str(request.data.get("profile_id") or "")), None)
        if not profile:
            return Response({"detail": "Choose a saved property search profile."}, status=404)
        try:
            days = int(request.data.get("days", 365))
        except (ValueError, TypeError):
            return Response({"detail": "Days must be a number."}, status=400)
        if days not in (30, 90, 180, 365, 730):
            return Response({"detail": "Choose 30, 90, 180, 365, or 730 days."}, status=400)
        cfg = settings()
        if not cfg:
            return Response({"detail": "Outlook connection is not configured."}, status=503)
        since = (timezone.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"$filter": "receivedDateTime ge " + since,
                  "$orderby": "receivedDateTime desc",
                  "$top": 100,
                  "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,webLink"}
        scanned = 0
        findings = []
        next_page = None
        more = False
        try:
            for page in range(3):
                if page == 0:
                    result = graph(request.user, cfg, str(account_id), "/me/messages", params=params)
                else:
                    parsed = urlparse(next_page or "")
                    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/me/messages"):
                        raise ValueError("Microsoft pagination URL rejected.")
                    token = access_token(request.user, cfg, str(account_id))
                    response = requests.get(next_page, headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/json",
                    }, timeout=20, allow_redirects=False)
                    if response.status_code != 200:
                        raise ValueError("Microsoft historical mail search failed.")
                    result = response.json()
                messages = (result.get("value") or [])[:100]
                scanned += len(messages)
                for message in messages:
                    matched = matches(message, profile)
                    if not matched:
                        continue
                    sender_address = str(((message.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
                    verified_contact = sender_address in profile["contacts"]
                    address = str(profile.get("property_address") or "").strip().lower()
                    context = (str(message.get("subject") or "") + " " + str(message.get("bodyPreview") or "")).lower()
                    explicit_property = bool(address and len(address) > 6 and address in context)
                    confidence = "STRONG" if verified_contact or explicit_property else "REVIEW_ONLY"
                    finding = classify(message)
                    findings.append({
                        "message_id": message.get("id"),
                        "subject": str(message.get("subject") or "(No subject)")[:200],
                        "sender": str(((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")[:180],
                        "received_at": message.get("receivedDateTime"),
                        "preview": str(message.get("bodyPreview") or "")[:500],
                        "matched_terms": matched,
                        "confidence": confidence,
                        "auto_attach_allowed": False,
                        "category": finding["category"] if finding else "REVIEW",
                        "priority": finding["priority"] if finding else "LOW",
                        "has_attachments": bool(message.get("hasAttachments")),
                        "outlook_url": message.get("webLink") if str(message.get("webLink") or "").startswith("https://outlook.") else None,
                        "verification": "MESSAGE_PREVIEW_ONLY",
                    })
                next_page = result.get("@odata.nextLink")
                if not next_page or not messages:
                    break
            more = bool(next_page)
        except (ValueError, requests.RequestException) as exc:
            logger.warning("Historical property correspondence scan failed")
            return Response({"detail": str(exc) if isinstance(exc, ValueError)
                             else "Microsoft mail search is unavailable."}, status=502)
        counts = dict(Counter(x["category"] for x in findings))
        return Response({
            "property": {"id": profile["profile_id"], "name": profile["name"],
                         "pm_property_id": profile.get("pm_property_id")},
            "mailbox": account["label"], "days": days, "scanned": scanned,
            "findings": findings, "counts": counts, "partial": more,
            "search_limit": MAX_MESSAGES,
            "notice": "Read-only historical search of recent messages across Outlook folders. It is limited to 300 messages per run; zero matches does not mean a matter is resolved.",
            "reconciliation": "No property balance or inspection status was independently verified.",
            "outlook_modified": False, "model_cost_usd": 0,
        })

class PropertyCorrespondenceReportView(APIView):
    """Attach explicitly reviewed Outlook references to an owned PM property.

    Never creates accounting transactions, changes Outlook, or asserts actual
    payment/inspection completion. Re-reads each selected message from Graph
    so client-provided subjects and categories cannot contaminate the record.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, property_id):
        prop = property_for_user(request.user, property_id)
        if not prop or not _pilot(request.user):
            return Response({"detail": "Property not accessible."}, status=404)
        events = AuditLog.objects.filter(actor=request.user, action=REPORT).order_by("-id")
        reports = [(e.metadata or {}) for e in events
                   if (e.metadata or {}).get("pm_property_id") == prop.id][:15]
        return Response({"property": {"id": prop.id, "name": prop.name},
                         "reports": reports})

    def post(self, request, property_id):
        prop = property_for_user(request.user, property_id)
        if not prop or not _pilot(request.user):
            return Response({"detail": "Property not accessible."}, status=404)
        mailbox_id = str(request.data.get("mailbox_id") or "")
        account = mailbox(request, mailbox_id)
        if not account:
            return Response({"detail": "Property mailbox not accessible."}, status=403)
        profile_id = str(request.data.get("profile_id") or "")
        profile = next((p for p in profiles(request.user, mailbox_id)
                        if p["profile_id"] == profile_id
                        and p.get("pm_property_id") == prop.id), None)
        if not profile:
            return Response({"detail": "Link this search profile to the property first."}, status=409)
        ids = request.data.get("message_ids")
        if not isinstance(ids, list) or not (1 <= len(ids) <= 20):
            return Response({"detail": "Select between 1 and 20 verified email references."}, status=400)
        if any(not isinstance(i, str) or not (1 <= len(i) <= 300) for i in ids) or len(set(ids)) != len(ids):
            return Response({"detail": "Invalid message reference."}, status=400)
        cfg = settings()
        if not cfg:
            return Response({"detail": "Outlook integration unavailable."}, status=503)
        references = []
        try:
            for identifier in ids:
                m = graph(request.user, cfg, mailbox_id,
                          "/me/messages/" + quote(identifier, safe=""),
                          params={"$select": "id,subject,from,receivedDateTime,bodyPreview,webLink"})
                matched = matches(m, profile)
                if not matched:
                    return Response({"detail": "A selected email no longer matches the property search."}, status=409)
                sender = str(((m.get("from") or {}).get("emailAddress") or {}).get("address") or "")
                finding = classify(m)
                references.append({
                    "message_id": m.get("id"),
                    "subject": str(m.get("subject") or "(No subject)")[:200],
                    "sender": sender[:180],
                    "received_at": m.get("receivedDateTime"),
                    "category": finding["category"] if finding else "REVIEW",
                    "matched_terms": matched[:10],
                    "outlook_url": m.get("webLink") if str(m.get("webLink") or "").startswith("https://outlook.") else None,
                    "status": "REVIEWED_EMAIL_REFERENCE_NOT_VERIFIED_PAYMENT",
                })
        except (requests.RequestException, ValueError):
            return Response({"detail": "Could not independently verify all selected emails with Outlook."}, status=502)
        report = {"report_id": str(uuid4()), "pm_property_id": prop.id,
                  "property_name": prop.name, "mailbox_id": mailbox_id,
                  "profile_id": profile_id, "created_at": timezone.now().isoformat(),
                  "category_counts": dict(Counter(r["category"] for r in references)),
                  "email_count": len(references), "references": references,
                  "status": "CORRESPONDENCE_REVIEW_ONLY",
                  "limitations": "Emails are not financial ledger proof, confirmation of funds received, or a completed inspection.",
                  "outlook_modified": False, "pm_ledger_modified": False}
        AuditLog.objects.create(actor=request.user, action=REPORT, metadata=report)
        return Response({"report": report, "notice": "Reviewed correspondence linked to PM property; no financial records or emails modified."}, status=201)
