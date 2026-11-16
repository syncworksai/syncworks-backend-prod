"""Private pilot Microsoft Outlook integration for Jarvis Chief of Staff.

Confidential OAuth authorization code flow, server-side encrypted token events,
read-only inbox listing, owner-reviewed reply/new-message drafts, and explicit
manual send. Never exposed to other SyncWorks users or unattended workers.
Required Render settings:
  SYNC_ASSIST_MS_CLIENT_ID
  SYNC_ASSIST_MS_CLIENT_SECRET
  SYNC_ASSIST_MS_REDIRECT_URI
  SYNC_ASSIST_MS_TOKEN_KEY  (Fernet key, independent of Django SECRET_KEY)
Register EXACT redirect URI on Microsoft Entra app (personal accounts allowed).
"""
import hashlib
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode

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
from .assist_pilot_views import _pilot, PILOT_EMAIL

GRAPH = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send"
APP_ORIGIN = "https://syncworksapp.com"
TOKEN_EVENT = "sync_assist.outlook.encrypted_token"
START_EVENT = "sync_assist.outlook.oauth_started"
CONSUMED_EVENT = "sync_assist.outlook.oauth_consumed"
DRAFT_EVENT = "sync_assist.outlook.draft_created"
SENT_EVENT = "sync_assist.outlook.draft_sent"
DISCONNECT_EVENT = "sync_assist.outlook.disconnected"


class IntegrationError(Exception):
    pass


def _settings():
    cid = os.environ.get("SYNC_ASSIST_MS_CLIENT_ID", "").strip()
    secret = os.environ.get("SYNC_ASSIST_MS_CLIENT_SECRET", "").strip()
    redirect = os.environ.get("SYNC_ASSIST_MS_REDIRECT_URI", "").strip()
    key = os.environ.get("SYNC_ASSIST_MS_TOKEN_KEY", "").strip()
    if not cid or not secret or not key or not redirect.startswith("https://"):
        return None
    try:
        cipher = Fernet(key.encode("ascii"))
    except (ValueError, TypeError):
        return None
    return cid, secret, redirect, cipher


def _latest(user):
    # Disconnect revokes local access; any preceding token events become ignored.
    events = AuditLog.objects.filter(actor=user, action__in=[TOKEN_EVENT, DISCONNECT_EVENT]).order_by("-id")
    event = events.first()
    if event is None or event.action == DISCONNECT_EVENT:
        return None
    return event


def _token(user, cfg):
    event = _latest(user)
    if not event:
        raise IntegrationError("Outlook not connected in SyncWorks.")
    try:
        secret = cfg[3].decrypt(event.metadata["encrypted"].encode("ascii")).decode("utf-8")
        import json
        value = json.loads(secret)
    except (KeyError, InvalidToken, ValueError, TypeError):
        raise IntegrationError("Outlook credential could not be decrypted; reconnect the mailbox.")
    if timezone.now().timestamp() < float(value.get("expires_at", 0))-90:
        return value["access_token"]
    refresh = value.get("refresh_token")
    if not refresh:
        raise IntegrationError("Outlook session expired; reconnect.")
    r = requests.post(AUTHORITY+"/token", data={
        "client_id": cfg[0], "client_secret": cfg[1],
        "grant_type": "refresh_token", "refresh_token": refresh,
        "scope": SCOPES,
    }, timeout=15)
    if r.status_code != 200:
        raise IntegrationError("Outlook authorization expired or was revoked; reconnect.")
    result = r.json()
    if not result.get("access_token"):
        raise IntegrationError("Outlook access token unavailable.")
    value.update({
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token") or refresh,
        "expires_at": timezone.now().timestamp()+int(result.get("expires_in",3600)),
    })
    _save_token(user,cfg,value)
    return value["access_token"]


def _save_token(user, cfg, value):
    import json
    encrypted=cfg[3].encrypt(json.dumps(value).encode("utf-8")).decode("ascii")
    AuditLog.objects.create(actor=user, action=TOKEN_EVENT, metadata={
        "encrypted": encrypted, "provider": "microsoft_graph", "encrypted_at_rest": True,
    })


def _graph(user, cfg, method, route, payload=None, params=None):
    access=_token(user,cfg)
    headers={"Authorization": "Bearer "+access, "Accept": "application/json", "Prefer": 'outlook.body-content-type="text"'}
    if payload is not None:
        headers["Content-Type"]="application/json"
    r=requests.request(method, GRAPH+route, headers=headers, json=payload, params=params, timeout=20)
    if r.status_code not in (200,201,202,204):
        if r.status_code in (401,403):
            raise IntegrationError("Outlook permission unavailable; reconnect and grant access.")
        if r.status_code == 404:
            raise IntegrationError("The Outlook message or draft no longer exists.")
        raise IntegrationError("Microsoft Graph could not complete this request.")
    return r.json() if r.content else {}


def _guard(request):
    if not _pilot(request.user):
        return Response({"detail": "Private pilot only."}, status=403)
    return None


class OutlookStatus(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        denied=_guard(request)
        if denied is not None: return denied
        cfg=_settings()
        return Response({
            "configured": bool(cfg),
            "connected": bool(cfg and _latest(request.user)),
            "outbound_automatic": False,
            "approval_required": True,
            "provider": "Microsoft Outlook",
            "setup_required": not bool(cfg),
            "notice": "Mail access belongs only to the authenticated pilot. Sending requires explicit confirmation per draft.",
        })


class OutlookConnect(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        denied=_guard(request)
        if denied is not None: return denied
        cfg=_settings()
        if not cfg: return Response({"detail":"Microsoft OAuth environment has not been configured."},status=503)
        nonce=secrets.token_urlsafe(24)
        AuditLog.objects.create(actor=request.user,action=START_EVENT,metadata={"nonce_hash":hashlib.sha256(nonce.encode()).hexdigest()})
        state=signing.dumps({"user":request.user.pk,"nonce":nonce},salt="sync-assist-outlook-oauth")
        auth=AUTHORITY+"/authorize?"+urlencode({
            "client_id":cfg[0],"response_type":"code","redirect_uri":cfg[2],
            "response_mode":"query","scope":SCOPES,"state":state,
            "prompt":"select_account",
        })
        return Response({"authorization_url":auth})


class OutlookCallback(APIView):
    authentication_classes=[]
    permission_classes=[AllowAny]
    def get(self,request):
        def redirect(status):
            return HttpResponseRedirect(APP_ORIGIN+"/sync/assist/email?connection="+status)
        cfg=_settings()
        if not cfg or request.query_params.get("error") or not request.query_params.get("code"):
            return redirect("error")
        try:
            state=signing.loads(request.query_params.get("state",""),salt="sync-assist-outlook-oauth",max_age=600)
            user=get_user_model().objects.get(pk=state["user"],is_active=True)
            if not _pilot(user): return redirect("error")
            hashed=hashlib.sha256(state["nonce"].encode()).hexdigest()
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                started=AuditLog.objects.filter(actor=user,action=START_EVENT,metadata__nonce_hash=hashed,created_at__gte=timezone.now()-timedelta(minutes=10)).exists()
                used=AuditLog.objects.filter(actor=user,action=CONSUMED_EVENT,metadata__nonce_hash=hashed).exists()
                if not started or used: return redirect("error")
                AuditLog.objects.create(actor=user,action=CONSUMED_EVENT,metadata={"nonce_hash":hashed})
            r=requests.post(AUTHORITY+"/token",data={
                "grant_type":"authorization_code","code":request.query_params["code"],
                "client_id":cfg[0],"client_secret":cfg[1],"redirect_uri":cfg[2],"scope":SCOPES,
            },timeout=20)
            if r.status_code != 200:return redirect("error")
            token=r.json()
            if not token.get("access_token") or not token.get("refresh_token"):return redirect("error")
            me=requests.get(GRAPH+"/me",headers={"Authorization":"Bearer "+token["access_token"]},timeout=15)
            if me.status_code!=200:return redirect("error")
            profile=me.json()
            addresses={str(profile.get("mail") or "").lower(),str(profile.get("userPrincipalName") or "").lower()}
            if PILOT_EMAIL not in addresses:
                return redirect("wrong_account")
            _save_token(user,cfg,{
                "access_token":token["access_token"],"refresh_token":token["refresh_token"],
                "expires_at":timezone.now().timestamp()+int(token.get("expires_in",3600)),
                "email":PILOT_EMAIL,
            })
            return redirect("connected")
        except (signing.BadSignature,ValueError,KeyError,TypeError,requests.RequestException,get_user_model().DoesNotExist):
            return redirect("error")


class OutlookInbox(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        denied=_guard(request)
        if denied is not None:return denied
        cfg=_settings()
        if not cfg or not _latest(request.user):
            return Response({"detail":"Outlook not connected in SyncWorks."},status=409)
        try:
            data=_graph(request.user,cfg,"GET","/me/mailFolders/inbox/messages",params={
                "$top":20,"$orderby":"receivedDateTime desc",
                "$select":"id,subject,from,receivedDateTime,bodyPreview,isRead,importance,conversationId",
            })
            return Response({"messages":[{
                "id":m.get("id"),"subject":m.get("subject") or "(No subject)",
                "from":m.get("from",{}).get("emailAddress",{}).get("address") or "",
                "received_at":m.get("receivedDateTime"),"preview":(m.get("bodyPreview") or "")[:300],
                "is_read":m.get("isRead"),"importance":m.get("importance"),
            } for m in data.get("value",[])],"automatic_morning_scan":False})
        except (IntegrationError,requests.RequestException) as e:
            return Response({"detail":str(e) if isinstance(e,IntegrationError) else "Outlook network error."},status=502)


class OutlookDraft(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        denied=_guard(request)
        if denied is not None:return denied
        cfg=_settings()
        if not cfg or not _latest(request.user):
            return Response({"detail":"Outlook not connected in SyncWorks."},status=409)
        body=str(request.data.get("body") or "").strip()
        subject=str(request.data.get("subject") or "").strip()
        recipient=str(request.data.get("recipient") or "").strip()
        reply_id=str(request.data.get("reply_to_id") or "").strip()
        if not body or len(body)>8000 or len(subject)>250 or len(recipient)>254 or len(reply_id)>1000:
            return Response({"detail":"Valid body, subject and recipient are required."},status=400)
        if not reply_id and (not subject or "@" not in recipient):
            return Response({"detail":"New messages need a recipient email and subject."},status=400)
        try:
            if reply_id:
                # The original must be visible within the authorized mailbox.
                original=_graph(request.user,cfg,"GET","/me/messages/"+requests.utils.quote(reply_id,safe=""),params={"$select":"id,subject,from"})
                actual=(original.get("from") or {}).get("emailAddress",{}).get("address") or ""
                if not actual or (recipient and recipient.casefold()!=actual.casefold()):
                    return Response({"detail":"Reply recipient must match the original sender."},status=400)
                recipient=actual
                draft=_graph(request.user,cfg,"POST","/me/messages/"+requests.utils.quote(reply_id,safe="")+"/createReply",payload={})
                did=draft.get("id")
                if not did:raise IntegrationError("Draft was not returned by Outlook.")
                _graph(request.user,cfg,"PATCH","/me/messages/"+requests.utils.quote(did,safe=""),payload={
                    "body":{"contentType":"Text","content":body},
                })
                subject=original.get("subject") or subject
            else:
                draft=_graph(request.user,cfg,"POST","/me/messages",payload={
                    "subject":subject,"body":{"contentType":"Text","content":body},
                    "toRecipients":[{"emailAddress":{"address":recipient}}],
                })
                did=draft.get("id")
                if not did:raise IntegrationError("Draft was not returned by Outlook.")
            AuditLog.objects.create(actor=request.user,action=DRAFT_EVENT,metadata={
                "draft_id":did, "recipient":recipient, "subject":subject,
                "body_sha256":hashlib.sha256(body.encode()).hexdigest(),
                "reply_to_id":reply_id, "sent":False,
            })
            return Response({"draft_id":did,"recipient":recipient,"subject":subject,"status":"draft_created","sent":False},status=201)
        except (IntegrationError,requests.RequestException) as e:
            return Response({"detail":str(e) if isinstance(e,IntegrationError) else "Outlook network error."},status=502)


class OutlookSend(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        denied=_guard(request)
        if denied is not None:return denied
        if request.data.get("confirmation")!="SEND":
            return Response({"detail":"Explicit SEND confirmation is required."},status=400)
        did=str(request.data.get("draft_id") or "")
        if not did or len(did)>1000:
            return Response({"detail":"Invalid draft ID."},status=400)
        cfg=_settings()
        if not cfg or not _latest(request.user):
            return Response({"detail":"Outlook not connected in SyncWorks."},status=409)
        # Serialize sends on the authenticated user; idempotency checks before sending.
        try:
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                record=AuditLog.objects.filter(actor=request.user,action=DRAFT_EVENT,metadata__draft_id=did).order_by("-id").first()
                if not record:return Response({"detail":"Only a draft created by this pilot account can be sent."},status=404)
                if AuditLog.objects.filter(actor=request.user,action=SENT_EVENT,metadata__draft_id=did).exists():
                    return Response({"detail":"This draft was already sent."},status=409)
                current=_graph(request.user,cfg,"GET","/me/messages/"+requests.utils.quote(did,safe=""),params={"$select":"id,isDraft,subject,body,toRecipients"})
                if not current.get("isDraft"):return Response({"detail":"This message is not an unsent draft."},status=409)
                actual_to=[v.get("emailAddress",{}).get("address","").lower() for v in current.get("toRecipients",[])]
                actual_body=(current.get("body") or {}).get("content") or ""
                if len(actual_to)!=1 or actual_to[0]!=record.metadata["recipient"].lower() or hashlib.sha256(actual_body.strip().encode()).hexdigest()!=record.metadata["body_sha256"]:
                    return Response({"detail":"Draft changed after review. Create a new reviewed draft before sending."},status=409)
                _graph(request.user,cfg,"POST","/me/messages/"+requests.utils.quote(did,safe="")+"/send",payload={})
                AuditLog.objects.create(actor=request.user,action=SENT_EVENT,metadata={"draft_id":did,"recipient":record.metadata["recipient"],"manual_confirmation":True})
            return Response({"sent":True,"draft_id":did,"recipient":record.metadata["recipient"]})
        except (IntegrationError,requests.RequestException) as e:
            return Response({"detail":str(e) if isinstance(e,IntegrationError) else "Outlook network error."},status=502)


class OutlookDisconnect(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request):
        denied=_guard(request)
        if denied is not None:return denied
        AuditLog.objects.create(actor=request.user,action=DISCONNECT_EVENT,metadata={"reason":"user_requested"})
        return Response({"connected":False,"notice":"SyncWorks token access disabled locally. Revoke app permissions in Microsoft account settings if desired."})
