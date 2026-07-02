from __future__ import annotations

from django.db import transaction
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
        business, _, _ = _business_context(request)
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
        )

        return Response(
            self.get_serializer(invitation).data,
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
