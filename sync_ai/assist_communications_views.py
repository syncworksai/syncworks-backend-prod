"""Private pilot communications hub.

No outbound messages or telephony. The webhook verifies Twilio request signatures
and accepts only the server-configured recipient. Never accept a customer-supplied
business ID, provider key, or user ID.
"""
import base64
import hashlib
import hmac
import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import PILOT_EMAIL, _pilot

INBOUND = "sync_assist.pilot.communication_inbound"
OUTBOUND_ENABLED = False
MAX_RESULTS = 50


def _number(value):
    return str(value or "").strip().lower().replace(" ", "")


def _configured():
    sender = _number(os.environ.get("SYNC_ASSIST_PILOT_WHATSAPP_TO"))
    secret = os.environ.get("TWILIO_AUTH_TOKEN", "")
    return bool(sender.startswith("whatsapp:+") and len(sender) > 12 and secret)


def _signature_valid(url, params, supplied, secret):
    # Twilio's application/x-www-form-urlencoded signature:
    # HMAC-SHA1(base64) of absolute URL followed by sorted form key/value pairs.
    if not supplied or not secret:
        return False
    signed = url + "".join(key + str(params.get(key, "")) for key in sorted(params.keys()))
    digest = base64.b64encode(hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")
    return hmac.compare_digest(digest, str(supplied))


def _list_messages(user):
    entries = AuditLog.objects.filter(actor=user, action=INBOUND).order_by("-id")[:MAX_RESULTS]
    return [{
        "id": str(item.metadata.get("message_sid", "")),
        "channel": "whatsapp",
        "direction": "inbound",
        "from": item.metadata.get("from", ""),
        "body": item.metadata.get("body", ""),
        "received_at": item.created_at.isoformat(),
        "status": "received",
    } for item in entries]


class SyncAssistCommunicationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response({
            "pilot": True,
            "whatsapp": {
                "status": "ready_for_inbound" if _configured() else "setup_required",
                "server_credentials_configured": _configured(),
                "sender_registration_verified": False,
                "outbound_enabled": False,
                "onboarding": "meta_twilio",
            },
            "sms": {"status": "not_connected"},
            "voice": {"status": "not_connected"},
            "messages": _list_messages(request.user),
            "notice": "Inbound messages require a verified Twilio sender and webhook. No automatic replies or calls.",
        })


@method_decorator(csrf_exempt, name="dispatch")
class SyncAssistWhatsAppInboundView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not _configured():
            return Response({"detail": "Channel inactive"}, status=503)
        if request.content_type != "application/x-www-form-urlencoded":
            return Response({"detail": "Unsupported content type"}, status=415)
        if len(request._request.body) > 16_384:
            return Response({"detail": "Payload too large"}, status=413)
        raw_form = request._request.POST
        if not _signature_valid(
            request.build_absolute_uri(), raw_form,
            request.headers.get("X-Twilio-Signature", ""),
            os.environ.get("TWILIO_AUTH_TOKEN", ""),
        ):
            return Response({"detail": "Signature invalid"}, status=403)
        target = _number(raw_form.get("To"))
        if target != _number(os.environ.get("SYNC_ASSIST_PILOT_WHATSAPP_TO")):
            return Response({"detail": "Unknown recipient"}, status=404)
        sender = _number(raw_form.get("From"))
        sid = str(raw_form.get("MessageSid") or "")
        body = str(raw_form.get("Body") or "")
        if not sender.startswith("whatsapp:+") or not sid.startswith("SM") or len(sid) > 64:
            return Response({"detail": "Invalid message"}, status=400)
        if len(body) > 4000:
            return Response({"detail": "Message too long"}, status=400)
        owner = get_user_model().objects.filter(email__iexact=PILOT_EMAIL, is_active=True).first()
        if owner is None:
            return Response({"detail": "Channel unavailable"}, status=503)
        # Lock the single account row to serialize concurrent webhook retries.
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=owner.pk)
            exists = AuditLog.objects.filter(actor=owner, action=INBOUND, metadata__message_sid=sid).exists()
            if not exists:
                AuditLog.objects.create(actor=owner, action=INBOUND, metadata={
                    "message_sid": sid, "from": sender, "to": target,
                    "body": body, "provider": "twilio", "no_reply": True,
                })
        # Twilio accepts an empty TwiML response; no outbound messages.
        from django.http import HttpResponse
        return HttpResponse("<Response></Response>", content_type="text/xml", status=200)
