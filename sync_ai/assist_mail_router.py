"""Read-only shared mailbox routing for SYNC Assist.

Only proposes a destination bot and filing action. Never changes Outlook.
Sensitive messages remain in Inbox; unrelated newsletters are proposed for
review, not archived. Uncertain messages go to Victoria for review.
"""
import re
from collections import Counter

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .assist_pilot_views import _pilot
from .assist_multi_mailbox_views import settings, snapshot, graph

PROPERTY = ("housing authority", "section 8", "section-8", "housing assistance",
            "mha", "hqs", "reinspection", "rent ledger", "rent collection",
            "abatement", "tenant rent", "lease agreement", "inspection report",
            "rental assistance", "property management", "landlord",
            "voucher", "work order")
SUPPORT = ("support ticket", "trouble logging in", "can't log in", "cannot log in",
           "bug report", "app error", "syncworks support", "customer complaint",
           "technical issue", "help desk", "account locked", "password reset")
BUSINESS = ("syncworks", "invoice", "new service request", "customer booking",
            "technician", "dispatch", "service ticket", "business account")
FINANCE = ("mortgage", "credit card statement", "autopay", "bill due",
           "payment reminder", "bank statement", "income payment",
           "payroll", "deposit received", "loan statement", "insurance premium",
           "payment past due", "student loan", "account past due")
MARKETS = ("stock market", "market outlook", "trading signals", "futures",
           "nasdaq", "s&p 500", "market recap", "brokerage", "robinhood",
           "topstep", "investment account")
GROWTH = ("upwork", "proposal accepted", "freelance", "business lead",
          "new lead", "marketing campaign", "client inquiry", "job posting")
PROMOTIONS = ("unsubscribe", "black friday", "half off", "50% off",
              "shop now", "discount code", "limited-time sale", "flash sale",
              "deal ends", "special offer")
HIGH = ("urgent", "action required", "deadline today", "final notice",
        "payment overdue", "failed inspection", "account locked",
        "security alert", "unusual sign-in")
PROTECTED = ("security alert", "verify your account", "court", "legal notice",
             "lawsuit", "fraud", "identity verification", "password reset",
             "medical", "tax notice")
ROLE = {
    "PROPERTY": "Sarah · Property Manager",
    "SUPPORT": "Customer Support",
    "BUSINESS": "Business Manager",
    "FINANCE": "Finance Manager",
    "MARKETS": "Trading Analyst",
    "GROWTH": "Elizabeth · Growth",
    "PERSONAL": "Personal Review",
    "REVIEW": "Victoria · Chief of Staff",
}
FOLDERS = {
    "PROPERTY": "SYNC / Property",
    "SUPPORT": "SYNC / Support",
    "BUSINESS": "SYNC / Business",
    "FINANCE": "SYNC / Finance",
    "MARKETS": "SYNC / Markets",
    "GROWTH": "SYNC / Growth",
    "PERSONAL": "SYNC / Personal",
    "REVIEW": "SYNC / Review",
}


def matches(text, terms):
    return any(term in text for term in terms)


def route(message):
    subject = str(message.get("subject") or "")[:200]
    preview = str(message.get("bodyPreview") or "")[:500]
    sender = str(((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")[:180]
    text = (subject + " " + preview + " " + sender).lower()
    context = (subject + " " + preview).lower()
    # Narrow brand-specific sender matches prevent debt and trading messages
    # from being misfiled as property-related simply because they mention money.
    property_evidence = matches(context, PROPERTY) or any(
        word in sender.lower() for word in
        ("housingauthority", "montgomeryhousing", "section8", "propertymanager"))
    explicit_support = matches(context, SUPPORT)
    explicit_markets = matches(context, MARKETS) or matches(sender.lower(), ("robinhood.", "topstep.", "fidelity.", "schwab."))
    explicit_finance = matches(context, FINANCE) or matches(sender.lower(), ("nelnet.", "experian.", "capitalone."))
    candidates = []
    if property_evidence: candidates.append("PROPERTY")
    if explicit_support: candidates.append("SUPPORT")
    if explicit_markets: candidates.append("MARKETS")
    if explicit_finance: candidates.append("FINANCE")
    if matches(context, BUSINESS): candidates.append("BUSINESS")
    if matches(context, GROWTH): candidates.append("GROWTH")
    candidates = list(dict.fromkeys(candidates))
    protected = matches(context, PROTECTED)
    priority = "HIGH" if matches(context, HIGH) or protected else "NORMAL"
    promotional = matches(context, PROMOTIONS)
    if len(candidates) > 1:
        # Conflicting labels must be resolved by a human, not guessed.
        category, confidence, reason = "REVIEW", "LOW", "Multiple possible work areas"
    elif len(candidates) == 1:
        category, confidence, reason = candidates[0], "MEDIUM", "Matched relevant mailbox content"
    elif promotional and not protected:
        category, confidence, reason = "PERSONAL", "MEDIUM", "Likely promotional mail"
    else:
        category, confidence, reason = "REVIEW", "LOW", "No reliable specialist match"
    if protected:
        category, confidence, reason = "REVIEW", "LOW", "Protected or sensitive correspondence"
    # No mailbox writes are currently enabled, even for high-confidence items.
    filing = "KEEP_IN_INBOX" if protected or priority == "HIGH" or category == "REVIEW" else "SUGGEST_FOLDER"
    return {
        "message_id": message.get("id"),
        "subject": subject or "(No subject)",
        "from": sender,
        "received_at": message.get("receivedDateTime"),
        "preview": preview,
        "category": category,
        "assistant": ROLE[category],
        "confidence": confidence,
        "priority": priority,
        "reason": reason,
        "proposed_folder": FOLDERS[category],
        "filing_action": filing,
        "outlook_modified": False,
    }


class AssistMailRoutingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        if not _pilot(request.user):
            return Response({"detail": "Not authorized."}, status=403)
        account = next((a for a in snapshot(request.user)
                        if a["account_id"] == str(account_id)), None)
        if not account:
            return Response({"detail": "Mailbox not connected."}, status=404)
        cfg = settings()
        if not cfg:
            return Response({"detail": "Mailbox connection is unavailable."}, status=503)
        try:
            result = graph(request.user, cfg, str(account_id),
                           "/me/mailFolders/inbox/messages", params={
                               "$top": 75, "$orderby": "receivedDateTime desc",
                               "$select": "id,subject,from,receivedDateTime,bodyPreview",
                           })
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=502)
        except Exception:
            return Response({"detail": "Could not read the inbox for routing."}, status=502)
        rows = [route(msg) for msg in (result.get("value") or [])[:75]]
        counts = dict(Counter(x["category"] for x in rows))
        important = [x for x in rows if x["priority"] == "HIGH" or x["category"] == "REVIEW"]
        return Response({
            "mailbox": {"label": account["label"], "email": account["email"]},
            "total": len(rows), "counts": counts,
            "needs_attention": len(important),
            "messages": rows,
            "brief": {
                "summary": f"{len(rows)} messages reviewed; {len(important)} require attention or classification review.",
                "specialist_queues": counts,
                "verified_actions": [],
            },
            "mode": "READ_ONLY_ROUTING_REVIEW",
            "archive_enabled": False, "move_enabled": False,
            "auto_filing_enabled": False,
            "scan_scope": "75 latest inbox messages; not a full-mailbox search",
            "warning": "Classification is provisional. No Outlook folders or messages were changed.",
        })
