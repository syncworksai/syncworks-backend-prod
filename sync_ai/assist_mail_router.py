"""Read-only shared mailbox routing for SYNC Assist.

Only proposes a destination bot and filing action. Never changes Outlook.
Sensitive messages remain in Inbox; unrelated newsletters are proposed for
review, not archived. Uncertain messages go to Victoria for review.
"""
import re
from collections import Counter
from user_accounts.models import AuditLog

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
           "debt collector", "debt collection", "settlement offer", "past due balance",
           "monthly payments", "your balances", "avoid default",
           "payment reminder", "bank statement", "income payment",
           "payroll", "deposit received", "loan statement", "insurance premium",
           "payment past due", "student loan", "account past due")
MARKETS = ("stock market", "market outlook", "trading signals", "futures",
           "nasdaq", "s&p 500", "market recap", "brokerage", "robinhood",
           "topstep", "investment account")
GROWTH = ("upwork", "proposal accepted", "freelance", "business lead",
          "new lead", "marketing campaign", "client inquiry", "job posting")
PROMOTIONS = ("unsubscribe", "black friday", "half off", "50% off",
              "offer is just for you", "redeem your offer", "redeem offer",
              "your exclusive offer", "promo", "coupon", "save today",
              "shop now", "discount code", "limited-time sale", "flash sale",
              "deal ends", "special offer")
DEBT_SENDERS = ("pacificdebt", "nationaldebtrelief", "freedomdebtrelief",
                "debtsettlement", "collections.")
PROMO_SENDERS = ("sionicdriven", "retailnewsletter", "deals.", "promotions.")
HIGH = ("urgent", "action required", "deadline today", "final notice",
        "payment overdue", "failed inspection", "account locked",
        "security alert", "unusual sign-in")
JOB_DISCOVERY = ("we're hiring", "we are hiring", "job alert", "job opportunity",
                 "new openings", "positions available", "recruiter", "hiring now",
                 "job matches", "apply for this role", "career opportunity",
                 "vacancy", "job recommendation", "open position")
JOB_ACTION = ("interview invitation", "interview scheduled", "your interview",
              "job offer letter", "offer of employment", "application update",
              "application received", "application status", "your application",
              "background check", "onboarding documents")
JOB_PREF_ACTION = "sync_assist.mail.job_preferences"
JOB_DEFAULT = {"job_search_active": False, "remote_only": True,
               "part_time_only": True, "keywords": [], "trusted_senders": []}
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


def job_prefs(user):
    event = AuditLog.objects.filter(actor=user, action=JOB_PREF_ACTION).order_by("-id").first()
    values = (event.metadata or {}) if event else {}
    return {**JOB_DEFAULT, **{key: values[key] for key in JOB_DEFAULT if key in values}}


def route(message, preferences=None):
    subject = str(message.get("subject") or "")[:200]
    preview = str(message.get("bodyPreview") or "")[:500]
    sender = str(((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")[:180]
    preferences = preferences or JOB_DEFAULT
    text = (subject + " " + preview + " " + sender).lower()
    context = (subject + " " + preview).lower()
    # Narrow brand-specific sender matches prevent debt and trading messages
    # from being misfiled as property-related simply because they mention money.
    property_evidence = matches(context, PROPERTY) or any(
        word in sender.lower() for word in
        ("housingauthority", "montgomeryhousing", "section8", "propertymanager"))
    explicit_support = matches(context, SUPPORT)
    explicit_markets = matches(context, MARKETS) or matches(sender.lower(), ("robinhood.", "topstep.", "fidelity.", "schwab."))
    debt_related = matches(context, ("debt collector", "debt collection", "debt settlement",
                                     "past due balance", "avoid default")) or matches(sender.lower(), DEBT_SENDERS)
    explicit_finance = debt_related or matches(context, FINANCE) or matches(sender.lower(), ("nelnet.", "experian.", "capitalone."))
    candidates = []
    if property_evidence: candidates.append("PROPERTY")
    if explicit_support: candidates.append("SUPPORT")
    if explicit_markets: candidates.append("MARKETS")
    if explicit_finance: candidates.append("FINANCE")
    if matches(context, BUSINESS): candidates.append("BUSINESS")
    if matches(context, GROWTH): candidates.append("GROWTH")
    candidates = list(dict.fromkeys(candidates))
    job_action = matches(context, JOB_ACTION)
    job_discovery = matches(context, JOB_DISCOVERY) and not job_action
    protected = matches(context, PROTECTED) or job_action
    priority = "HIGH" if matches(context, HIGH) or protected else "NORMAL"
    promotional = matches(context, PROMOTIONS) or matches(sender.lower(), PROMO_SENDERS)
    # Broad generic matches are common in marketing emails. Do not allow a
    # promotion to masquerade as customer-support or Growth work.
    if promotional and not property_evidence and not explicit_support and not explicit_finance and not explicit_markets:
        candidates = []
    if job_discovery and not property_evidence and not explicit_support:
        keyword_filter = [str(w).lower() for w in preferences.get("keywords", [])]
        trusted = any(str(w).lower() in sender.lower()
                      for w in preferences.get("trusted_senders", []))
        relevant = ((not preferences.get("remote_only") or "remote" in context)
                    and (not preferences.get("part_time_only")
                         or matches(context, ("part-time", "part time", "contract", "freelance")))
                    and (not keyword_filter or any(w in context for w in keyword_filter)))
        if not preferences.get("job_search_active", False):
            candidates = []
            category, confidence, reason = "PERSONAL", "MEDIUM", "Job search paused: proposed filing only"
        elif relevant or trusted:
            candidates = []
            category, confidence, reason = "GROWTH", "MEDIUM", "Job opportunity matches active preferences"
        else:
            candidates = []
            category, confidence, reason = "PERSONAL", "MEDIUM", "Job alert does not match preferences"
    elif len(candidates) > 1:
        # Conflicting labels must be resolved by a human, not guessed.
        category, confidence, reason = "REVIEW", "LOW", "Multiple possible work areas"
    elif len(candidates) == 1:
        category, confidence, reason = candidates[0], "MEDIUM", "Matched relevant mailbox content"
    elif promotional and not protected:
        category, confidence, reason = "PERSONAL", "MEDIUM", "Likely promotional mail"
    else:
        category, confidence, reason = "REVIEW", "LOW", "No reliable specialist match"
    if protected:
        category, confidence, reason = "REVIEW", "LOW", "Protected correspondence or an existing job application"
    if debt_related and category == "FINANCE":
        priority, reason = "HIGH", "Debt correspondence requires financial review"
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
        "job_alert": job_discovery,
        "job_action": job_action,
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
        preferences = job_prefs(request.user)
        rows = [route(msg, preferences) for msg in (result.get("value") or [])[:75]]
        counts = dict(Counter(x["category"] for x in rows))
        important = [x for x in rows if x["priority"] == "HIGH" or x["category"] == "REVIEW"]
        return Response({
            "mailbox": {"label": account["label"], "email": account["email"]},
            "total": len(rows), "counts": counts, "job_preferences": preferences,
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

    def patch(self, request, account_id):
        if not _pilot(request.user):
            return Response({"detail": "Not authorized."}, status=403)
        if not any(a["account_id"] == str(account_id) for a in snapshot(request.user)):
            return Response({"detail": "Mailbox not connected."}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        values = job_prefs(request.user)
        for key in ("job_search_active", "remote_only", "part_time_only"):
            if key in data:
                if not isinstance(data[key], bool):
                    return Response({"detail": key + " must be a boolean."}, status=400)
                values[key] = data[key]
        for key in ("keywords", "trusted_senders"):
            if key in data:
                if not isinstance(data[key], list) or len(data[key]) > 12 or any(
                    not isinstance(v, str) or len(v) > 80 for v in data[key]
                ):
                    return Response({"detail": key + " must contain up to 12 short phrases."}, status=400)
                values[key] = [v.strip().lower() for v in data[key] if v.strip()]
        AuditLog.objects.create(actor=request.user, action=JOB_PREF_ACTION,
                                metadata=values)
        return Response({"job_preferences": values, "filing_enabled": False,
                         "notice": "Preferences saved. Outlook has not been modified."})
