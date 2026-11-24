"""Owner-scoped multi-Outlook inboxes: distinct OAuth grants and read-only mailbox access.

Private founder pilot is free. Future customer subscription entitlement is
deliberately fail-closed; no customer is charged or given free extra mailboxes
without a verified billing integration.
"""
import hashlib
import json
import logging
import re
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import uuid4, UUID

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot

GRAPH = "https://graph.microsoft.com/v1.0"
AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPES = "offline_access User.Read Mail.Read"
EVENT = "sync_assist.mailbox.connected"
LABEL = "sync_assist.mailbox.label"
REMOVED = "sync_assist.mailbox.removed"
START = "sync_assist.mailbox.oauth_started"
CONSUMED = "sync_assist.mailbox.oauth_used"
MAX_PILOT_MAILBOXES = 10
CATEGORIES = {"PERSONAL", "PROPERTY", "SYNCWORKS", "FINANCE", "OTHER"}
PRIORITIES = {"CRITICAL", "HIGH", "NORMAL", "LOW"}
SITE = "https://syncworksapp.com"
STATE_SALT = "sync-assist-multi-mailbox-oauth-v1"
logger = logging.getLogger(__name__)

def settings():
    cid = os.getenv("SYNC_ASSIST_MS_CLIENT_ID", "").strip()
    secret = os.getenv("SYNC_ASSIST_MS_CLIENT_SECRET", "").strip()
    key = os.getenv("SYNC_ASSIST_MS_TOKEN_KEY", "").strip()
    redirect = os.getenv("SYNC_ASSIST_MS_MULTI_REDIRECT_URI", "").strip()
    if not (cid and secret and redirect.startswith("https://") and key):
        return None
    try:
        cipher = Fernet(key.encode("ascii"))
    except (ValueError, TypeError):
        return None
    return cid, secret, redirect, cipher

def owner_only(request):
    if not _pilot(request.user):
        return Response({"detail": "Additional inboxes require an active paid entitlement. Billing for additional customer inboxes is not active; no charge was created."}, status=403)
    return None

def normalize_id(raw):
    try:
        return str(UUID(str(raw)))
    except (ValueError, TypeError, AttributeError):
        return None

def snapshot(user):
    items = {}
    for event in AuditLog.objects.filter(actor=user, action__in=[EVENT,LABEL,REMOVED]).order_by("id"):
        m = event.metadata or {}
        key = m.get("account_id")
        if not normalize_id(key):
            continue
        if event.action == EVENT:
            items[key] = {"account_id":key, "email":m.get("email",""),
                "label":m.get("label",""), "category":m.get("category","OTHER"),
                "priority":m.get("priority","NORMAL"), "connected_at":event.created_at.isoformat(),
                "connected":True}
        elif event.action == LABEL and key in items:
            items[key].update({k:m[k] for k in ("label","category","priority") if k in m})
        elif event.action == REMOVED and key in items:
            items[key]["connected"] = False
    return [v for v in items.values() if v["connected"]]

def account_event(user, identifier):
    events = AuditLog.objects.filter(actor=user,action__in=[EVENT,REMOVED],metadata__account_id=identifier).order_by("-id")
    last = events.first()
    return last if last and last.action == EVENT else None

def encrypt(cfg, token):
    return cfg[3].encrypt(json.dumps(token).encode("utf-8")).decode("ascii")

def decrypt(cfg, record):
    try:
        return json.loads(cfg[3].decrypt(record.metadata["encrypted"].encode("ascii")).decode("utf-8"))
    except (KeyError,ValueError,TypeError,InvalidToken):
        raise ValueError("Mailbox credential invalid. Disconnect and reconnect this account.")

def access_token(user, cfg, identifier):
    record = account_event(user,identifier)
    if record is None:
        raise ValueError("Mailbox is not connected.")
    token = decrypt(cfg,record)
    if timezone.now().timestamp() < float(token.get("expires_at",0)) - 90:
        return token["access_token"]
    if not token.get("refresh_token"):
        raise ValueError("Mailbox access expired. Reconnect the account.")
    try:
        r = requests.post(AUTH+"/token",data={
            "client_id":cfg[0],"client_secret":cfg[1],"grant_type":"refresh_token",
            "refresh_token":token["refresh_token"],"scope":SCOPES},timeout=15)
        r.raise_for_status()
        updated = r.json()
        if not updated.get("access_token"):
            raise ValueError()
    except (requests.RequestException, ValueError):
        raise ValueError("Microsoft authorization expired; reconnect this mailbox.")
    token.update({"access_token":updated["access_token"],
        "refresh_token":updated.get("refresh_token") or token["refresh_token"],
        "expires_at":timezone.now().timestamp()+int(updated.get("expires_in",3600))})
    meta = dict(record.metadata)
    meta["encrypted"] = encrypt(cfg,token)
    AuditLog.objects.create(actor=user,action=EVENT,metadata=meta)
    return token["access_token"]

def graph(user,cfg,identifier,route,params=None):
    token = access_token(user,cfg,identifier)
    response = requests.get(GRAPH+route,headers={"Authorization":"Bearer "+token,
        "Accept":"application/json"},params=params,timeout=20)
    if response.status_code in (401,403):
        raise ValueError("Microsoft rejected this mailbox grant; reconnect.")
    if response.status_code != 200:
        raise ValueError("Could not retrieve Microsoft mail; retry later.")
    return response.json()

class MultiMailboxView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request):
        denied=owner_only(request)
        if denied is not None:return denied
        return Response({"configured":bool(settings()),"accounts":snapshot(request.user),
            "pilot_free":True,"pilot_limit":MAX_PILOT_MAILBOXES,
            "additional_inbox_price_usd_month":"9.99",
            "future_billing_status":"NOT_ENABLED",
            "provider":"Microsoft Outlook",
            "notice":"Pilot mailboxes are free. Each mailbox is isolated and read-only. Paid customer mailbox entitlements must be verified before activation."})
    def patch(self,request):
        denied=owner_only(request)
        if denied is not None:return denied
        identifier=normalize_id(request.data.get("account_id"))
        label=str(request.data.get("label") or "").strip()
        category=str(request.data.get("category") or "OTHER").upper()
        priority=str(request.data.get("priority") or "NORMAL").upper()
        if not identifier or not account_event(request.user,identifier):
            return Response({"detail":"Mailbox not found."},status=404)
        if not 1<=len(label)<=50 or category not in CATEGORIES or priority not in PRIORITIES:
            return Response({"detail":"Provide a label (1–50 characters), valid category and priority."},status=400)
        AuditLog.objects.create(actor=request.user,action=LABEL,metadata={
            "account_id":identifier,"label":label,"category":category,"priority":priority})
        return Response({"accounts":snapshot(request.user)})
    def delete(self,request):
        denied=owner_only(request)
        if denied is not None:return denied
        identifier=normalize_id(request.data.get("account_id"))
        if not identifier or not account_event(request.user,identifier):
            return Response({"detail":"Mailbox not found."},status=404)
        AuditLog.objects.create(actor=request.user,action=REMOVED,metadata={"account_id":identifier})
        return Response({"accounts":snapshot(request.user),
            "notice":"Mailbox access removed from SyncWorks. Revoke consent in Microsoft if you also want to revoke the provider authorization."})

class MultiMailboxConnect(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        denied=owner_only(request)
        if denied is not None:return denied
        cfg=settings()
        if cfg is None:
            return Response({"detail":"Microsoft OAuth is not configured on Render. Administrator setup required."},status=503)
        if len(snapshot(request.user))>=MAX_PILOT_MAILBOXES:
            return Response({"detail":"Private pilot mailbox limit reached."},status=429)
        label=str(request.data.get("label") or "").strip()
        category=str(request.data.get("category") or "OTHER").upper()
        priority=str(request.data.get("priority") or "NORMAL").upper()
        if not 1<=len(label)<=50 or category not in CATEGORIES or priority not in PRIORITIES:
            return Response({"detail":"Choose a mailbox label, category and priority."},status=400)
        nonce=secrets.token_urlsafe(30)
        digest=hashlib.sha256(nonce.encode()).hexdigest()
        AuditLog.objects.create(actor=request.user,action=START,metadata={"nonce_hash":digest})
        state=signing.dumps({"user_id":request.user.pk,"nonce":nonce,
            "label":label,"category":category,"priority":priority},salt=STATE_SALT)
        url=AUTH+"/authorize?"+urlencode({"client_id":cfg[0],"response_type":"code",
            "redirect_uri":cfg[2],"response_mode":"query","scope":SCOPES,
            "state":state,"prompt":"select_account"})
        return Response({"authorization_url":url})

class MultiMailboxCallback(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        # Never expose Microsoft authorization codes, tokens, or secrets in
        # redirects or application logs. Only stable error categories are shown.
        def finish(stage):
            return HttpResponseRedirect(
                SITE + "/sync/assist/email?mailbox_connection=" + stage
            )

        cfg = settings()
        if cfg is None:
            return finish("config_missing")
        if request.query_params.get("error"):
            microsoft_error = str(request.query_params.get("error") or "").lower()
            logger.warning("Multi-mailbox OAuth rejected by Microsoft: %s",
                           re.sub(r"[^a-z_]", "", microsoft_error)[:50])
            if microsoft_error == "access_denied":
                return finish("consent_denied")
            return finish("microsoft_rejected")
        if not request.query_params.get("code"):
            return finish("authorization_missing")

        stage = "state_invalid"
        try:
            state = signing.loads(request.query_params.get("state", ""),
                                  salt=STATE_SALT, max_age=600)
            user = get_user_model().objects.get(pk=state["user_id"], is_active=True)
            if not _pilot(user):
                return finish("unauthorized")

            stage = "state_expired"
            digest = hashlib.sha256(state["nonce"].encode()).hexdigest()
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                started = AuditLog.objects.filter(
                    actor=user, action=START, metadata__nonce_hash=digest,
                    created_at__gte=timezone.now()-timedelta(minutes=10)).exists()
                used = AuditLog.objects.filter(
                    actor=user, action=CONSUMED, metadata__nonce_hash=digest).exists()
                if not started or used:
                    return finish("state_expired")
                AuditLog.objects.create(actor=user, action=CONSUMED,
                                        metadata={"nonce_hash":digest})

            stage = "token_exchange_failed"
            response = requests.post(AUTH + "/token", data={
                "grant_type":"authorization_code",
                "code":request.query_params["code"],
                "client_id":cfg[0],
                "client_secret":cfg[1],
                "redirect_uri":cfg[2],
                "scope":SCOPES,
            }, timeout=20)
            if response.status_code != 200:
                # Microsoft may provide AADSTS numeric codes. Only the number
                # is logged; full descriptions may contain account information.
                microsoft_code = re.search(r"AADSTS(\d{5,8})",
                    str(response.text or "")[:5000])
                logger.warning("Multi-mailbox token exchange failed: http=%s aadsts=%s",
                               response.status_code,
                               microsoft_code.group(1) if microsoft_code else "unknown")
                return finish("token_exchange_failed")
            token = response.json()
            if not token.get("access_token") or not token.get("refresh_token"):
                return finish("token_incomplete")

            stage = "profile_failed"
            profile = requests.get(GRAPH + "/me", headers={
                "Authorization":"Bearer " + token["access_token"]
            }, timeout=15)
            if profile.status_code != 200:
                logger.warning("Multi-mailbox profile lookup failed: http=%s",
                               profile.status_code)
                return finish("profile_failed")
            account = profile.json()
            email = str(account.get("mail") or account.get("userPrincipalName") or "").strip().lower()
            if not email or "@" not in email or len(email) > 254:
                return finish("account_missing")

            stage = "save_failed"
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                existing = snapshot(user)
                old = next((v for v in existing if v["email"].lower() == email), None)
                if len(existing) >= MAX_PILOT_MAILBOXES and not old:
                    return finish("limit")
                account_id = old["account_id"] if old else str(uuid4())
                AuditLog.objects.create(actor=user, action=EVENT, metadata={
                    "account_id":account_id,
                    "email":email,
                    "label":str(state["label"])[:50],
                    "category":state["category"],
                    "priority":state["priority"],
                    "encrypted":encrypt(cfg, {
                        "access_token":token["access_token"],
                        "refresh_token":token["refresh_token"],
                        "expires_at":timezone.now().timestamp() + int(token.get("expires_in",3600)),
                    }),
                    "provider":"microsoft_graph",
                    "encrypted_at_rest":True,
                })
            return finish("connected")
        except signing.SignatureExpired:
            return finish("state_expired")
        except signing.BadSignature:
            logger.warning("Multi-mailbox callback state signature invalid; verify OAuth start and callback use Ohio backend")
            return finish("state_invalid")
        except get_user_model().DoesNotExist:
            logger.warning("Multi-mailbox OAuth callback user not present on callback backend")
            return finish("account_context_mismatch")
        except (KeyError, TypeError):
            logger.warning("Multi-mailbox callback state missing required fields")
            return finish("state_invalid")
        except requests.Timeout:
            return finish("provider_timeout")
        except requests.RequestException:
            return finish("provider_unavailable")
        except (ValueError, json.JSONDecodeError):
            return finish(stage)
        except Exception:
            logger.exception("Multi-mailbox OAuth callback failed at stage=%s", stage)
            return finish(stage)

class MultiMailboxInbox(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request,account_id):
        denied=owner_only(request)
        if denied is not None:return denied
        identifier=normalize_id(account_id)
        if identifier is None or not account_event(request.user,identifier):
            return Response({"detail":"Mailbox not found."},status=404)
        cfg=settings()
        if not cfg:return Response({"detail":"Outlook authorization not configured."},status=503)
        try:
            data=graph(request.user,cfg,identifier,"/me/mailFolders/inbox/messages",params={
                "$top":25,"$orderby":"receivedDateTime desc",
                "$select":"id,subject,from,receivedDateTime,bodyPreview,isRead,importance"})
        except (ValueError,requests.RequestException) as exc:
            return Response({"detail":str(exc) if isinstance(exc,ValueError) else "Microsoft is temporarily unavailable."},status=502)
        messages=[{"id":m.get("id"),"subject":m.get("subject") or "(No subject)",
            "from":((m.get("from") or {}).get("emailAddress") or {}).get("address") or "",
            "received_at":m.get("receivedDateTime"),"preview":str(m.get("bodyPreview") or "")[:300],
            "is_read":m.get("isRead"),"importance":m.get("importance")}
            for m in data.get("value",[])]
        return Response({"account_id":identifier,"messages":messages,
            "read_only":True,"automatic_scanning_enabled":False})
