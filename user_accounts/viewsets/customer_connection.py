"""Secure email-based connection from a business CRM contact to a SyncWorks customer.

An invitation never creates an account or exposes tickets to an unverified email.
The recipient signs in, verifies the matching address, then claims the signed link.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog, BusinessCustomer, Ticket, Notification

logger = logging.getLogger(__name__)
SALT = "syncworks-business-customer-link-v1"
MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def invitation_token(ticket, customer):
    return signing.dumps({
        "ticket":ticket.pk, "customer":customer.pk, "business":customer.business_id,
        "email":customer.email.strip().casefold(),
    },salt=SALT)


def send_customer_invitation(ticket_id, customer_id):
    ticket = Ticket.objects.select_related("assigned_business","operations_profile").filter(pk=ticket_id).first()
    customer = BusinessCustomer.objects.select_related("business").filter(pk=customer_id).first()
    if not ticket or not customer or not customer.email or ticket.business_customer_id != customer.id:
        return
    email = customer.email.strip().lower()
    # One welcome per business/contact, not an invite on every service call.
    if AuditLog.objects.filter(action="business.customer_connection_invited",
                               metadata__business_id=customer.business_id,
                               metadata__customer_id=customer.pk).exists():
        return
    url = (getattr(settings,"FRONTEND_URL","https://syncworksapp.com") or "https://syncworksapp.com").rstrip("/")
    link = f"{url}/customer/connect?{urlencode({'token':invitation_token(ticket,customer)})}"
    start = getattr(getattr(ticket,"operations_profile",None),"scheduled_start",None)
    when = timezone.localtime(start).strftime("%a %b %d at %I:%M %p") if start else "To be scheduled"
    subject = f"{customer.business.name} invited you to SyncWorks"
    body = (
        f"Hello {customer.name or 'there'},\n\n"
        f"{customer.business.name} created a service request for you: {ticket.work_title}.\n"
        f"Appointment: {when}.\n\n"
        "Use SyncWorks to view service updates, appointments, and messages from this business. "
        "You can create a free account or sign in to your existing account. "
        "For your privacy, you must verify the same email address this invitation was sent to.\n\n"
        f"Connect your service request: {link}\n\n"
        "This link expires in 14 days. If you didn't request service, contact the business directly.\n"
    )
    try:
        count = send_mail(subject,body,getattr(settings,"DEFAULT_FROM_EMAIL",None),[email],fail_silently=False)
        if count:
            AuditLog.objects.create(action="business.customer_connection_invited",
                                    metadata={"business_id":customer.business_id,
                                              "customer_id":customer.pk,"ticket_id":ticket.pk})
        else:
            logger.warning("Customer invitation not delivered: customer_id=%s",customer.pk)
    except Exception:
        logger.exception("Failed to send customer invitation: customer_id=%s",customer.pk)


class CustomerConnectionClaimView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        raw = str(request.data.get("token") or "")
        try:
            data = signing.loads(raw,salt=SALT,max_age=MAX_AGE_SECONDS)
        except (signing.BadSignature,signing.SignatureExpired):
            return Response({"detail":"This invitation is invalid or expired. Ask the business to resend it."},status=400)
        if not request.user.email_verified:
            return Response({"detail":"Verify your account email address before connecting this service request."},status=403)
        if request.user.email.strip().casefold() != data.get("email"):
            return Response({"detail":"Sign in with the verified email address that received the invitation."},status=403)
        customer = BusinessCustomer.objects.select_for_update().filter(
            pk=data.get("customer"), business_id=data.get("business")
        ).first()
        if not customer or customer.email.strip().casefold()!=data.get("email"):
            return Response({"detail":"Customer invitation is no longer valid."},status=404)
        ticket = Ticket.objects.filter(
            pk=data.get("ticket"),business_customer=customer,assigned_business_id=customer.business_id
        ).first()
        if not ticket:
            return Response({"detail":"This service request is no longer available."},status=404)
        # The CRM contact represents a single verified recipient and one business.
        # Connect only this contact's tickets, never other customers at the business.
        linked = list(Ticket.objects.filter(
            business_customer=customer,assigned_business_id=customer.business_id
        ).select_for_update())
        from user_accounts.services.personal_calendar_sync import sync_ticket_to_personal_calendar
        for item in linked:
            if item.customer_visible and item.customer_id != request.user.id:
                continue
            item.customer = request.user
            item.customer_visible = True
            item.customer_status_label = "Connected to verified SyncWorks customer"
            item.save(update_fields=["customer","customer_visible","customer_status_label"])
            sync_ticket_to_personal_calendar(item)
        Notification.objects.create(
            recipient=request.user,type=Notification.TYPE_TICKET,
            title=f"Connected with {customer.business.name}",
            body=f"Your service requests with {customer.business.name} are available in SyncWorks.",
            data={"source":"TICKET","business_id":customer.business_id,
                  "ticket_id":ticket.pk,"target_path":"/customer"},
        )
        return Response({"connected":True,"business_name":customer.business.name,
                         "ticket_id":ticket.pk,"connected_tickets":len(linked)})
