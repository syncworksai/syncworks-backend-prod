from __future__ import annotations

from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape
from datetime import timedelta
from urllib.parse import urlencode
import logging
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_affiliates.models import AffiliatePartner, ReferralAttribution
from user_accounts.models import (
    Business,
    BusinessPartnerInvitation,
    BusinessPartnerRelationship,
    ServiceCategory,
)
from user_accounts.serializers.partner_network import (
    BusinessPartnerInvitationSerializer,
    BusinessPartnerRelationshipSerializer,
    PartnerBusinessCardSerializer,
)
from user_accounts.viewsets.ticket_conversations import _business_context


logger = logging.getLogger(__name__)


def _email_partner_invitation(invitation_id):
    invitation = BusinessPartnerInvitation.objects.select_related('inviting_business').filter(pk=invitation_id).first()
    if not invitation or not invitation.email:
        return
    root = (getattr(settings,'FRONTEND_URL','https://syncworksapp.com') or 'https://syncworksapp.com').rstrip('/')
    url = f"{root}/partner/join?{urlencode({'token':invitation.token})}"
    name = invitation.contact_name or invitation.business_name or 'there'
    subject = f"{invitation.inviting_business.name} invited you to work through SyncWorks"
    body = (f"Hello {name},\n\n{invitation.inviting_business.name} invited you to connect as a subcontractor on SyncWorks.\n\n"
            f"You can review offers, accept or decline work, and receive job updates once you connect an account with this email.\n"
            f"{invitation.message[:500]}\n\nAccept your invitation: {url}\n\n"
            "The invitation expires in 14 days. A paid SyncWorks business subscription is not required just to receive this invitation. "
            "Full business management tools are offered separately.\n"
            "If you weren't expecting this invitation, you can ignore this email.\n")
    # Table layout and inline styles keep the invitation readable in Gmail,
    # Outlook and mobile mail apps without relying on images or external fonts.
    safe_business = escape(invitation.inviting_business.name)
    safe_name = escape(name)
    safe_url = escape(url)
    optional_message = (
        f'<tr><td style="padding:0 32px 18px;color:#b9cbdf;font-size:14px;line-height:22px;">'
        f'{escape(invitation.message[:500])}</td></tr>'
        if invitation.message else ''
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:28px 12px;background:#071021;font-family:Arial,Helvetica,sans-serif;color:#f4f8ff;">
<table role="presentation" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;margin:0 auto;border-collapse:collapse;">
<tr><td style="height:5px;background:#20d4f2;border-radius:16px 16px 0 0;"></td></tr>
<tr><td style="background:#0b1930;border:1px solid #254363;border-top:none;border-radius:0 0 16px 16px;padding:0;">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">
<tr><td style="padding:30px 32px 10px;"><span style="font-size:16px;letter-spacing:2px;font-weight:bold;color:#eef6ff;">SYNCWORKS</span><br><span style="font-size:11px;letter-spacing:2px;color:#66dffa;">PARTNER NETWORK</span></td></tr>
<tr><td style="padding:14px 32px 4px;font-size:27px;line-height:34px;font-weight:700;color:#ffffff;">You’re invited to work together.</td></tr>
<tr><td style="padding:12px 32px 18px;font-size:15px;line-height:24px;color:#c9d8e9;">Hello {safe_name},<br><strong style="color:#ffffff;">{safe_business}</strong> invited you to join its subcontractor network on SyncWorks.</td></tr>
<tr><td style="padding:0 32px 20px;font-size:14px;line-height:23px;color:#b9cbdf;">One place to receive job offers, respond to assignments, and stay informed as work progresses.</td></tr>
{optional_message}
<tr><td align="center" style="padding:4px 32px 20px;"><a href="{safe_url}" style="display:block;background:#20cbe8;border-radius:10px;padding:15px 20px;color:#061426;text-align:center;font-size:16px;font-weight:700;text-decoration:none;">Review your invitation</a></td></tr>
<tr><td style="padding:0 32px 22px;font-size:12px;line-height:20px;color:#a6bcd4;">New to SyncWorks? Create a free account using this invited email address. Already a member? Sign in or switch accounts on the invitation page. No paid business subscription is required to receive this invitation.</td></tr>
<tr><td style="padding:17px 32px;border-top:1px solid #254363;color:#829db9;font-size:12px;line-height:20px;">Invitation expires in 14 days. If the button does not work, copy this link into your browser:<br><a href="{safe_url}" style="color:#6bddff;overflow-wrap:anywhere;word-break:break-word;">{safe_url}</a><br><br>If you weren't expecting this invitation, you can ignore this email.</td></tr>
</table></td></tr></table></body></html>"""
    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=getattr(settings,'DEFAULT_FROM_EMAIL',None),
            to=[invitation.email],
        )
        message.attach_alternative(html, 'text/html')
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Partner invite email failed for invitation %s',invitation_id)


def _owner_affiliate_code(business: Business) -> str:
    affiliate = AffiliatePartner.objects.filter(
        user=business.owner,
    ).first()
    return affiliate.code if affiliate else ""


def _apply_partner_affiliate_attribution(
    invitation: BusinessPartnerInvitation,
    target_business: Business,
    user,
) -> bool:
    if ReferralAttribution.objects.filter(
        business=target_business,
    ).exists():
        return False

    code = (invitation.affiliate_code or "").strip()
    if not code:
        return False

    affiliate = AffiliatePartner.objects.filter(code=code).first()
    if not affiliate:
        return False

    ReferralAttribution.objects.create(
        business=target_business,
        affiliate=affiliate,
        referral_code=affiliate.code,
        attribution_source="LINK",
        assigned_by=user,
        admin_note=(
            "Automatically attributed from accepted "
            "SyncWorks partner-network invitation."
        ),
    )
    return True


class BusinessPartnerRelationshipViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessPartnerRelationshipSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        business, _, _ = _business_context(self.request)
        return (
            BusinessPartnerRelationship.objects.filter(
                Q(hiring_business=business) | Q(partner_business=business)
            )
            .select_related(
                "hiring_business",
                "partner_business",
                "invited_by",
                "accepted_by",
            )
            .prefetch_related("services_allowed")
            .distinct()
        )

    def partial_update(self, request, *args, **kwargs):
        relationship = self.get_object()
        business, _, _ = _business_context(request)

        allowed = {
            "preferred_partner",
            "default_markup_type",
            "default_markup_value",
            "payment_terms_days",
            "insurance_verified",
            "license_verified",
            "compliance_notes",
            "internal_notes",
        }
        payload = {
            key: value
            for key, value in request.data.items()
            if key in allowed
        }

        if business.id != relationship.hiring_business_id:
            payload = {
                key: value
                for key, value in payload.items()
                if key in {"compliance_notes"}
            }

        service_ids = request.data.get("service_ids")
        serializer = self.get_serializer(
            relationship,
            data=payload,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        relationship = serializer.save()

        if (
            service_ids is not None
            and business.id == relationship.hiring_business_id
        ):
            if not isinstance(service_ids, list):
                raise ValidationError(
                    {"service_ids": "Use a list of category IDs."}
                )
            services = ServiceCategory.objects.filter(
                id__in=service_ids,
                is_active=True,
            )
            relationship.services_allowed.set(services)

        return Response(self.get_serializer(relationship).data)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        relationship = self.get_object()
        business, _, _ = _business_context(request)
        requested = str(request.data.get("status") or "").strip().upper()
        allowed_statuses = {
            value for value, _ in BusinessPartnerRelationship.Status.choices
        }
        if requested not in allowed_statuses:
            raise ValidationError({"status": "Unknown relationship status."})

        if requested == BusinessPartnerRelationship.Status.ACTIVE:
            if business.id != relationship.partner_business_id:
                raise ValidationError(
                    {"status": "Only the partner business can activate."}
                )
            relationship.accepted_by = request.user
            relationship.accepted_at = timezone.now()
        elif requested in {
            BusinessPartnerRelationship.Status.SUSPENDED,
            BusinessPartnerRelationship.Status.TERMINATED,
        }:
            if business.id not in {
                relationship.hiring_business_id,
                relationship.partner_business_id,
            }:
                raise ValidationError({"status": "Access denied."})
        elif requested == BusinessPartnerRelationship.Status.DECLINED:
            if business.id != relationship.partner_business_id:
                raise ValidationError(
                    {"status": "Only the partner business can decline."}
                )

        relationship.status = requested
        relationship.save(
            update_fields=[
                "status",
                "accepted_by",
                "accepted_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(relationship).data)


class BusinessPartnerInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessPartnerInvitationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        business, _, _ = _business_context(self.request)
        user_email = (self.request.user.email or "").strip()
        return (
            BusinessPartnerInvitation.objects.filter(
                Q(inviting_business=business)
                | Q(target_business=business)
                | Q(email__iexact=user_email)
            )
            .select_related(
                "inviting_business",
                "target_business",
                "relationship",
                "relationship__hiring_business",
                "relationship__partner_business",
                "created_by",
            )
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        business, membership, oversight = _business_context(request)
        if not oversight:
            raise ValidationError({"detail":"Team management permission required to invite partners."})
        target_id = request.data.get("target_business")
        email = str(request.data.get("email") or "").strip().lower()
        phone = str(request.data.get("phone") or "").strip()
        business_name = str(
            request.data.get("business_name") or ""
        ).strip()

        target = None
        if target_id not in (None, ""):
            try:
                target = Business.objects.get(
                    id=int(target_id),
                    is_active=True,
                )
            except (ValueError, Business.DoesNotExist):
                raise ValidationError(
                    {"target_business": "Business was not found."}
                )
            if target.id == business.id:
                raise ValidationError(
                    {"target_business": "A business cannot invite itself."}
                )

        if not target and not email and not phone:
            raise ValidationError(
                {"contact": "Provide a business, email, or phone."}
            )

        relationship_type = str(
            request.data.get("relationship_type")
            or BusinessPartnerRelationship.RelationshipType.SUBCONTRACTOR
        ).strip().upper()
        valid_types = {
            value
            for value, _ in BusinessPartnerRelationship.RelationshipType.choices
        }
        if relationship_type not in valid_types:
            raise ValidationError(
                {"relationship_type": "Unknown relationship type."}
            )

        if target and BusinessPartnerRelationship.objects.filter(
            hiring_business=business,
            partner_business=target,
        ).exclude(
            status=BusinessPartnerRelationship.Status.TERMINATED
        ).exists():
            raise ValidationError(
                {"target_business": "This partner relationship already exists."}
            )

        invitation = BusinessPartnerInvitation.objects.create(
            inviting_business=business,
            target_business=target,
            contact_name=str(
                request.data.get("contact_name") or ""
            ).strip(),
            email=email or (target.business_email if target else ""),
            phone=phone or (target.phone if target else ""),
            business_name=business_name or (target.name if target else ""),
            relationship_type=relationship_type,
            message=str(request.data.get("message") or "").strip(),
            affiliate_code=_owner_affiliate_code(business),
            created_by=request.user,
            expires_at=timezone.now()+timedelta(days=14),
        )
        if invitation.email:
            transaction.on_commit(lambda invitation_id=invitation.id: _email_partner_invitation(invitation_id))

        return Response(
            {**self.get_serializer(invitation).data, "email_queued":bool(invitation.email)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="business-search")
    def business_search(self, request):
        business, _, _ = _business_context(request)
        query = str(request.query_params.get("q") or "").strip()
        if len(query) < 2:
            raise ValidationError(
                {"q": "Enter at least two characters."}
            )

        businesses = (
            Business.objects.filter(is_active=True)
            .exclude(id=business.id)
            .filter(
                Q(name__icontains=query)
                | Q(business_email__icontains=query)
                | Q(phone__icontains=query)
                | Q(base_zip__icontains=query)
            )
            .order_by("name")[:25]
        )
        return Response(
            PartnerBusinessCardSerializer(businesses, many=True).data
        )

    @action(detail=False, methods=["post"], url_path="respond")
    def respond(self, request):
        business, _, _ = _business_context(request)
        token = str(request.data.get("token") or "").strip()
        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()

        invitation = BusinessPartnerInvitation.objects.filter(
            token=token,
            status=BusinessPartnerInvitation.Status.PENDING,
        ).select_related("inviting_business").first()
        if not invitation:
            raise ValidationError(
                {"token": "Invitation was not found or is no longer pending."}
            )

        if (
            invitation.expires_at
            and invitation.expires_at <= timezone.now()
        ):
            invitation.status = BusinessPartnerInvitation.Status.EXPIRED
            invitation.responded_at = timezone.now()
            invitation.save(
                update_fields=["status", "responded_at"]
            )
            raise ValidationError({"token": "Invitation has expired."})

        email_matches = (
            invitation.email
            and invitation.email.lower()
            == (request.user.email or "").strip().lower()
        )
        business_matches = invitation.target_business_id == business.id
        if invitation.target_business_id and not business_matches:
            raise ValidationError(
                {"business": "Invitation targets another business."}
            )
        if not invitation.target_business_id and not email_matches:
            raise ValidationError(
                {
                    "email": (
                        "Sign in with the invited email address before "
                        "accepting this invitation."
                    )
                }
            )

        if invitation.email and not getattr(request.user,"email_verified",False):
            raise ValidationError({"email":"Verify the invited email address before accepting a partner invitation."})

        if decision not in {"ACCEPT", "DECLINE"}:
            raise ValidationError(
                {"decision": "Use ACCEPT or DECLINE."}
            )

        if decision == "DECLINE":
            invitation.status = BusinessPartnerInvitation.Status.DECLINED
            invitation.target_business = business
            invitation.responded_at = timezone.now()
            invitation.save(
                update_fields=[
                    "status",
                    "target_business",
                    "responded_at",
                ]
            )
            return Response(self.get_serializer(invitation).data)

        if business.id == invitation.inviting_business_id:
            raise ValidationError(
                {"business": "A business cannot partner with itself."}
            )

        with transaction.atomic():
            relationship, created = (
                BusinessPartnerRelationship.objects.get_or_create(
                    hiring_business=invitation.inviting_business,
                    partner_business=business,
                    defaults={
                        "relationship_type": invitation.relationship_type,
                        "status": BusinessPartnerRelationship.Status.ACTIVE,
                        "invited_by": invitation.created_by,
                        "accepted_by": request.user,
                        "accepted_at": timezone.now(),
                    },
                )
            )
            if not created:
                relationship.relationship_type = (
                    invitation.relationship_type
                )
                relationship.status = (
                    BusinessPartnerRelationship.Status.ACTIVE
                )
                relationship.accepted_by = request.user
                relationship.accepted_at = timezone.now()
                relationship.save(
                    update_fields=[
                        "relationship_type",
                        "status",
                        "accepted_by",
                        "accepted_at",
                        "updated_at",
                    ]
                )

            invitation.target_business = business
            invitation.relationship = relationship
            invitation.status = (
                BusinessPartnerInvitation.Status.ACCEPTED
            )
            invitation.responded_at = timezone.now()
            invitation.save(
                update_fields=[
                    "target_business",
                    "relationship",
                    "status",
                    "responded_at",
                ]
            )

            attributed = _apply_partner_affiliate_attribution(
                invitation,
                business,
                request.user,
            )

        payload = self.get_serializer(invitation).data
        payload["affiliate_attribution_created"] = attributed
        return Response(payload)
