"""Owner-scoped multi-Outlook inboxes: distinct OAuth grants and read-only mailbox access.

Private founder pilot is free. Future customer subscription entitlement is
deliberately fail-closed; no customer is charged or given free extra mailboxes
without a verified billing integration.
"""
import hashlib
import json
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
    authentication_classes=[]
    permission_classes=[AllowAny]
    def get(self,request):
        def finish(code):
            return HttpResponseRedirect(SITE+"/sync/assist/email?mailbox_connection="+code)
        cfg=settings()
        if cfg is None or request.query_params.get("error") or not request.query_params.get("code"):
            return finish("error")
        try:
            state=signing.loads(request.query_params.get("state",""),salt=STATE_SALT,max_age=600)
            user=get_user_model().objects.get(pk=state["user_id"],is_active=True)
            if not _pilot(user):return finish("unauthorized")
            hashed=hashlib.sha256(state["nonce"].encode()).hexdigest()
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                started=AuditLog.objects.filter(actor=user,action=START,metadata__nonce_hash=hashed,
                    created_at__gte=timezone.now()-timedelta(minutes=10)).exists()
                used=AuditLog.objects.filter(actor=user,action=CONSUMED,metadata__nonce_hash=hashed).exists()
                if not started or used:return finish("expired")
                AuditLog.objects.create(actor=user,action=CONSUMED,metadata={"nonce_hash":hashed})
            response=requests.post(AUTH+"/token",data={
                "grant_type":"authorization_code","code":request.query_params["code"],
                "client_id":cfg[0],"client_secret":cfg[1],"redirect_uri":cfg[2],
                "scope":SCOPES},timeout=20)
            if response.status_code!=200:return finish("error")
            token=response.json()
            if not token.get("access_token") or not token.get("refresh_token"):
                return finish("error")
            profile=requests.get(GRAPH+"/me",headers={"Authorization":"Bearer "+token["access_token"]},timeout=15)
            if profile.status_code!=200:return finish("error")
            p=profile.json()
            email=str(p.get("mail") or p.get("userPrincipalName") or "").strip().lower()
            if not email or "@" not in email or len(email)>254:return finish("error")
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                if len(snapshot(user))>=MAX_PILOT_MAILBOXES:return finish("limit")
                old=next((v for v in snapshot(user) if v["email"].lower()==email),None)
                account_id=old["account_id"] if old else str(uuid4())
                AuditLog.objects.create(actor=user,action=EVENT,metadata={
                    "account_id":account_id,"email":email,"label":state["label"][:50],
                    "category":state["category"],"priority":state["priority"],
                    "encrypted":encrypt(cfg,{"access_token":token["access_token"],
                        "refresh_token":token["refresh_token"],
                        "expires_at":timezone.now().timestamp()+int(token.get("expires_in",3600))}),
                    "provider":"microsoft_graph","encrypted_at_rest":True})
            return finish("connected")
        except (signing.BadSignature,ValueError,KeyError,TypeError,requests.RequestException,get_user_model().DoesNotExist):
            return finish("error")

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
