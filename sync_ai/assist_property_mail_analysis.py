"""Sarah's bounded, read-only property correspondence triage.

Manual scan only. Processes up to 75 recent inbox previews, never sends mail,
writes calendar items, asserts balances, or invents inspections. Every finding
references a specific Microsoft message identifier and a literal preview.
The analysis is deterministic and costs no language-model tokens.
"""
import re
import logging
from collections import Counter

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog

from .assist_pilot_views import _pilot
from .assist_multi_mailbox_views import (
    settings as mailbox_settings, snapshot, graph,
)

logger = logging.getLogger(__name__)
SCAN_ACTION = "sync_assist.property.mail_scan"
CATEGORIES = {
    "INSPECTION": ("inspection", "reinspection", "re-inspection", "inspector",
                   "failed inspection", "pass inspection", "housing quality",
                   "hqs", "smoke detector", "certificate of occupancy"),
    "PAYMENT": ("housing assistance payment", "rent payment",
                "housing payment", "missing funds", "payment adjustment",
                "abatement", "abated", "reimbursement", "rent ledger",
                "disbursement", "payment received", "deposit", "past due"),
    "DOCUMENTS": ("lease agreement", "rental agreement", "certificate of occupancy",
                  "inspection report", "statement of account", "ledger request",
                  "document request", "notice of abatement"),
    "TENANT": ("tenant", "section 8", "voucher", "property management",
               "landlord", "housing authority", "mha", "rent increase"),
}
SENDER_HINTS = ("housing", "section8", "section-8", "landlord", "property",
                "montgomeryhousing", "mha")
URGENT = ("urgent", "action required", "deadline", "final notice", "overdue",
          "failed inspection", "abatement", "payment suspended")
FOLLOWUP = ("please respond", "please confirm", "please provide", "please send",
            "please advise", "can you confirm", "could you", "requesting",
            "schedule an inspection", "need to schedule", "please schedule")
SALES = ("unsubscribe", "sale ends", "black friday", "discount", "promo code",
         "shop now", "book your appointment", "newsletter", "special offer")
# Strong property association is required before Sarah sees a financial message.
# Generic words (payment, transfer, deposit, overdue) do not prove that a
# message concerns rent or housing assistance.
PROPERTY_SENDER_TERMS = ("housingauthority", "housing-authority", "section8",
    "section-8", "montgomeryhousing", "propertymanager", "property-management",
    "landlord", "rentcafe")
PROPERTY_SUBJECT_TERMS = ("section 8", "housing authority", "rental assistance",
    "housing assistance", "rent ledger", "tenant rent", "rent collection",
    "rent increase", "lease", "reinspection", "inspection", "abatement",
    "property management", "landlord", "housing voucher", "housing quality",
    "smoke detector", "certificate of occupancy", "work order")
NON_PROPERTY_SENDER_TERMS = ("robinhood.com", "nelnet.", "creditkarma.",
    "capitalone.", "experian.", "coinbase.", "topstep.", "fidelity.",
    "schwab.", "etrade.", "newsletter.", "marketing.")
NON_PROPERTY_SUBJECT_TERMS = ("instant deposit", "trading", "investment",
    "credit card", "stock market", "crypto", "black friday", "personal loan",
    "account is past due", "avoid default", "funds available for investing")
MAX_SCAN = 75
MAX_FINDINGS = 30


def _signal(value, choices):
    return any(x in value for x in choices)


def _clean(value, limit):
    return re.sub(r"\\s+", " ", str(value or "")).strip()[:limit]


def classify(message):
    subject = _clean(message.get("subject"), 200)
    preview = _clean(message.get("bodyPreview"), 500)
    sender = _clean(((message.get("from") or {}).get("emailAddress") or {}).get("address"), 180)
    sender_l = sender.lower()
    content = (subject + " " + preview).lower()
    # Ignore marketing messages unless they have a genuine property-management signal.
    category = next((cat for cat, terms in CATEGORIES.items()
                     if _signal(content, terms)), None)
    if not category and re.search(r"\\b(hap|mha|hqs|coo|section\\s*8)\\b", content):
        category = "PAYMENT" if re.search(r"\\bhap\\b", content) else "TENANT"
    sender_property = _signal(sender_l, PROPERTY_SENDER_TERMS)
    subject_property = _signal(content, PROPERTY_SUBJECT_TERMS) or bool(
        re.search(r"\\b(section\\s*8|mha|hqs|hap)\\b", content))
    explicit_property = sender_property or subject_property
    unrelated_finance = (_signal(sender_l, NON_PROPERTY_SENDER_TERMS) or
                         _signal(content, NON_PROPERTY_SUBJECT_TERMS))
    if unrelated_finance and not explicit_property:
        return None
    if _signal(content, SALES) and not explicit_property:
        return None
    # Generic finance-related subjects must go to a finance bot, not Sarah.
    if not explicit_property:
        return None
    if not category:
        category = "REVIEW"
    urgency = "HIGH" if _signal(content, URGENT) else (
        "MEDIUM" if _signal(content, FOLLOWUP) or category in {"INSPECTION", "PAYMENT"}
        else "LOW")
    # Priority indicates review order only, not a proven missed deadline.
    if category == "INSPECTION":
        next_action = "Verify inspection status and proposed date in the full message; request confirmation if unresolved."
    elif category == "PAYMENT":
        next_action = "Compare the referenced payment against the property ledger and housing authority statement before asserting any amount owed."
    elif category == "DOCUMENTS":
        next_action = "Check whether the requested document has been received and filed; identify any missing attachment."
    elif category == "TENANT":
        next_action = "Review the correspondence and verify which property and tenant it concerns."
    else:
        next_action = "Review the message to determine whether it concerns an active managed property."
    raw_date = _clean(message.get("receivedDateTime"), 45)
    return {
        "message_id": message.get("id"),
        "subject": subject or "(No subject)",
        "from": sender,
        "received_at": raw_date,
        "preview": preview,
        "category": category,
        "priority": urgency,
        "proposed_action": next_action,
        "evidence_type": "INBOX_PREVIEW",
        "fact_status": "NEEDS_SOURCE_VERIFICATION",
        "proposed_reply": {
            "subject": "Re: " + subject[:140] if subject else "Request for property correspondence update",
            "to": sender,
            "body": (
                "Hello,\\n\\nThank you for your message regarding "
                + ("the inspection" if category == "INSPECTION" else
                   "the payment or housing assistance" if category == "PAYMENT" else
                   "the property management matter")
                + ". Could you please confirm the current status, any outstanding "
                  "requirements, and the next steps or expected timeline? "
                  "Please include any supporting documentation available.\\n\\n"
                  "Thank you,\\nProperty Management"
            ),
            "send_enabled": False,
        },
    }


class SarahPropertyMailAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, account_id):
        if not _pilot(request.user):
            return Response({"detail": "This email analysis is not enabled for this account."}, status=403)
        account = next((a for a in snapshot(request.user)
                        if a["account_id"] == str(account_id)), None)
        if not account:
            return Response({"detail": "No connected mailbox with this ID."}, status=404)
        if account.get("category") != "PROPERTY":
            return Response({"detail": "Label the mailbox as Property before running Sarah's analysis."}, status=400)
        cfg = mailbox_settings()
        if not cfg:
            return Response({"detail": "Microsoft mailbox authorization is not configured."}, status=503)
        try:
            source = graph(request.user, cfg, str(account_id),
                           "/me/mailFolders/inbox/messages",
                           params={
                               "$top": MAX_SCAN,
                               "$orderby": "receivedDateTime desc",
                               "$select": "id,subject,from,receivedDateTime,bodyPreview,importance",
                           })
        except ValueError as err:
            return Response({"detail": str(err)}, status=502)
        except Exception:
            logger.exception("Sarah property mail read failed (no message content logged)")
            return Response({"detail": "Microsoft inbox could not be read. Retry or reconnect."}, status=502)

        messages = (source.get("value") or [])[:MAX_SCAN]
        findings = [f for m in messages if (f := classify(m)) is not None][:MAX_FINDINGS]
        findings.sort(key=lambda f: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f["priority"]])
        counts = dict(Counter(f["category"] for f in findings))
        checked_at = timezone.now().isoformat()
        # Only non-sensitive execution metadata is persisted: never subjects, bodies,
        # addresses, message IDs, or analysis drafts in AuditLog.
        AuditLog.objects.create(actor=request.user, action=SCAN_ACTION, metadata={
            "account_id": str(account_id), "checked_at": checked_at,
            "sample_size": len(messages), "finding_count": len(findings),
            "category_counts": counts, "mode": "MANUAL_READ_ONLY_RULES",
        })
        return Response({
            "assistant": "Sarah",
            "mailbox": {"account_id": str(account_id), "label": account.get("label"),
                        "category": account.get("category")},
            "checked_at": checked_at,
            "scanned": len(messages),
            "limit": MAX_SCAN,
            "partial_sample": bool(source.get("@odata.nextLink")),
            "findings": findings,
            "counts": counts,
            "report": {
                "inspection": "Messages classified as inspection-related are leads to review, not confirmation an inspection is scheduled.",
                "payments": "No payment amounts, arrears, or reimbursements have been reconciled with the housing authority or landlord ledger.",
                "next_step": "Open the underlying correspondence, verify dates and attachments, and approve any proposed response before sending.",
            },
            "capabilities": {"model_calls": 0, "automatic_monitoring": False,
                             "sending": False, "drafts_are_suggestions": True,
                             "calendar_writes": False, "payment_actions": False},
        })

    def get(self, request, account_id):
        if not _pilot(request.user):
            return Response({"detail": "Not authorized."}, status=403)
        if not any(a["account_id"] == str(account_id) for a in snapshot(request.user)):
            return Response({"detail": "Mailbox not connected."}, status=404)
        latest = AuditLog.objects.filter(actor=request.user, action=SCAN_ACTION,
                 metadata__account_id=str(account_id)).order_by("-id").first()
        return Response({"last_run": (latest.metadata if latest else None),
                         "notice": "Detailed findings are not stored; run a fresh scan to view the current report."})
