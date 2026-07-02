from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    BusinessMember,
    BusinessPartnerRelationship,
    PartnerWorkTicket,
    Ticket,
)
from user_accounts.serializers.partner_work_tickets import (
    PartnerWorkTicketSerializer,
)
from user_accounts.viewsets.ticket_conversations import _business_context


PARTNER_EDITABLE_STATUSES = {
    PartnerWorkTicket.Status.SCHEDULED,
    PartnerWorkTicket.Status.EN_ROUTE,
    PartnerWorkTicket.Status.ON_SITE,
    PartnerWorkTicket.Status.IN_PROGRESS,
    PartnerWorkTicket.Status.BLOCKED,
    PartnerWorkTicket.Status.AWAITING_REVIEW,
}

SOURCE_STATUS_MAP = {
    PartnerWorkTicket.Status.ACCEPTED: Ticket.Status.ACCEPTED,
    PartnerWorkTicket.Status.SCHEDULED: Ticket.Status.SCHEDULED,
    PartnerWorkTicket.Status.EN_ROUTE: Ticket.Status.EN_ROUTE,
    PartnerWorkTicket.Status.ON_SITE: Ticket.Status.ON_SITE,
    PartnerWorkTicket.Status.IN_PROGRESS: Ticket.Status.IN_PROGRESS,
    PartnerWorkTicket.Status.BLOCKED: Ticket.Status.IN_PROGRESS,
    PartnerWorkTicket.Status.AWAITING_REVIEW: Ticket.Status.AWAITING_APPROVAL,
    PartnerWorkTicket.Status.COMPLETED: Ticket.Status.COMPLETED,
}


class PartnerWorkTicketViewSet(viewsets.ModelViewSet):
    serializer_class = PartnerWorkTicketSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _business(self):
        business, _, _ = _business_context(self.request)
        return business

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            context["active_business_id"] = self._business().id
        except Exception:
            context["active_business_id"] = None
        return context

    def get_queryset(self):
        business = self._business()
        return (
            PartnerWorkTicket.objects.filter(
                Q(hiring_business=business) | Q(partner_business=business)
            )
            .select_related(
                "relationship",
                "source_ticket",
                "source_ticket__project",
                "hiring_business",
                "partner_business",
                "assigned_member",
                "offered_by",
                "accepted_by",
                "reviewed_by",
            )
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        business = self._business()

        try:
            relationship_id = int(request.data.get("relationship"))
            source_ticket_id = int(request.data.get("source_ticket"))
        except (TypeError, ValueError):
            raise ValidationError(
                {
                    "relationship": "Use a numeric relationship ID.",
                    "source_ticket": "Use a numeric source ticket ID.",
                }
            )

        relationship = BusinessPartnerRelationship.objects.filter(
            id=relationship_id,
            hiring_business=business,
            status=BusinessPartnerRelationship.Status.ACTIVE,
        ).select_related("partner_business").first()
        if not relationship:
            raise ValidationError(
                {"relationship": "An active outbound partner is required."}
            )

        source_ticket = Ticket.objects.filter(
            id=source_ticket_id,
            assigned_business=business,
        ).select_related(
            "business_customer",
            "customer",
        ).first()
        if not source_ticket:
            raise ValidationError(
                {"source_ticket": "Source ticket was not found."}
            )
        if hasattr(source_ticket, "partner_work_ticket"):
            raise ValidationError(
                {"source_ticket": "This ticket already has partner work."}
            )

        allowed_services = relationship.services_allowed.all()
        if (
            allowed_services.exists()
            and source_ticket.category_id
            and not allowed_services.filter(
                id=source_ticket.category_id
            ).exists()
        ):
            raise ValidationError(
                {
                    "source_ticket": (
                        "The partner is not approved for this service category."
                    )
                }
            )

        share_contact = bool(request.data.get("share_customer_contact", False))
        customer = source_ticket.business_customer
        customer_user = source_ticket.customer
        contact_name = ""
        contact_email = ""
        contact_phone = ""
        if share_contact:
            if customer:
                contact_name = customer.name or customer.company_name or ""
                contact_email = customer.email or ""
                contact_phone = customer.phone or ""
            else:
                contact_name = (
                    customer_user.get_full_name()
                    or getattr(customer_user, "email", "")
                    or ""
                )
                contact_email = getattr(customer_user, "email", "") or ""

        with transaction.atomic():
            work = PartnerWorkTicket.objects.create(
                relationship=relationship,
                source_ticket=source_ticket,
                hiring_business=business,
                partner_business=relationship.partner_business,
                title=(
                    str(request.data.get("title") or "").strip()
                    or source_ticket.work_title
                    or source_ticket.ticket_code
                ),
                scope=(
                    str(request.data.get("scope") or "").strip()
                    or source_ticket.work_scope
                ),
                service_address=source_ticket.service_address,
                service_zip=source_ticket.service_zip,
                access_instructions=str(
                    request.data.get("access_instructions") or ""
                ).strip(),
                share_customer_contact=share_contact,
                customer_contact_name=contact_name,
                customer_contact_email=contact_email,
                customer_contact_phone=contact_phone,
                agreed_amount_cents=max(
                    int(request.data.get("agreed_amount_cents") or 0),
                    0,
                ),
                hiring_business_notes=str(
                    request.data.get("hiring_business_notes") or ""
                ).strip(),
                shared_updates=str(
                    request.data.get("shared_updates") or ""
                ).strip(),
                scheduled_at=request.data.get("scheduled_at") or None,
                offered_by=request.user,
            )
            source_ticket.status = Ticket.Status.ASSIGNED
            source_ticket.assigned_at = (
                source_ticket.assigned_at or timezone.now()
            )
            source_ticket.save(
                update_fields=["status", "assigned_at"]
            )

        return Response(
            self.get_serializer(work).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        work = self.get_object()
        business = self._business()

        if business.id == work.hiring_business_id:
            allowed = {
                "scope",
                "access_instructions",
                "share_customer_contact",
                "agreed_amount_cents",
                "hiring_business_notes",
                "shared_updates",
                "scheduled_at",
            }
        else:
            allowed = {
                "partner_internal_cost_cents",
                "partner_internal_notes",
                "shared_updates",
                "completion_summary",
                "blocked_reason",
                "scheduled_at",
            }

        for key in allowed:
            if key not in request.data:
                continue
            value = request.data.get(key)
            if key in {
                "agreed_amount_cents",
                "partner_internal_cost_cents",
            }:
                try:
                    value = max(int(value or 0), 0)
                except (TypeError, ValueError):
                    raise ValidationError({key: "Use a whole number of cents."})
            setattr(work, key, value)

        if "share_customer_contact" in request.data:
            work.share_customer_contact = bool(
                request.data.get("share_customer_contact")
            )

        work.save()
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=["post"], url_path="respond")
    def respond(self, request, pk=None):
        work = self.get_object()
        business = self._business()
        if business.id != work.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can respond."}
            )
        if work.status != PartnerWorkTicket.Status.OFFERED:
            raise ValidationError(
                {"status": "This work offer is no longer pending."}
            )

        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()
        if decision not in {"ACCEPT", "DECLINE"}:
            raise ValidationError(
                {"decision": "Use ACCEPT or DECLINE."}
            )

        now = timezone.now()
        if decision == "ACCEPT":
            work.status = PartnerWorkTicket.Status.ACCEPTED
            work.accepted_by = request.user
            work.accepted_at = now
            work.source_ticket.status = Ticket.Status.ACCEPTED
            work.source_ticket.accepted_at = now
            work.source_ticket.save(
                update_fields=["status", "accepted_at"]
            )
        else:
            work.status = PartnerWorkTicket.Status.DECLINED
            work.declined_at = now
            work.source_ticket.status = Ticket.Status.NEW
            work.source_ticket.assigned_at = None
            work.source_ticket.save(
                update_fields=["status", "assigned_at"]
            )

        work.save()
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=["post"], url_path="assign-member")
    def assign_member(self, request, pk=None):
        work = self.get_object()
        business = self._business()
        if business.id != work.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can assign its team."}
            )

        try:
            user_id = int(request.data.get("user_id"))
        except (TypeError, ValueError):
            raise ValidationError({"user_id": "Use a numeric user ID."})

        member = BusinessMember.objects.filter(
            business=business,
            user_id=user_id,
            is_active=True,
        ).select_related("user").first()
        if not member:
            raise ValidationError(
                {"user_id": "User is not an active business member."}
            )

        work.assigned_member = member.user
        work.save(update_fields=["assigned_member", "updated_at"])
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        work = self.get_object()
        business = self._business()
        if business.id != work.partner_business_id:
            raise ValidationError(
                {"business": "Only the partner business can update work status."}
            )

        requested = str(
            request.data.get("status") or ""
        ).strip().upper()
        if requested not in PARTNER_EDITABLE_STATUSES:
            raise ValidationError(
                {
                    "status": (
                        "Use SCHEDULED, EN_ROUTE, ON_SITE, IN_PROGRESS, "
                        "BLOCKED, or AWAITING_REVIEW."
                    )
                }
            )
        if work.status in {
            PartnerWorkTicket.Status.OFFERED,
            PartnerWorkTicket.Status.DECLINED,
            PartnerWorkTicket.Status.COMPLETED,
            PartnerWorkTicket.Status.CANCELLED,
        }:
            raise ValidationError(
                {"status": "Current work status cannot be changed."}
            )

        now = timezone.now()
        work.status = requested
        if requested == PartnerWorkTicket.Status.SCHEDULED:
            work.scheduled_at = (
                request.data.get("scheduled_at")
                or work.scheduled_at
                or now
            )
        elif requested == PartnerWorkTicket.Status.IN_PROGRESS:
            work.started_at = work.started_at or now
        elif requested == PartnerWorkTicket.Status.BLOCKED:
            work.blocked_reason = str(
                request.data.get("blocked_reason")
                or work.blocked_reason
                or ""
            ).strip()
        elif requested == PartnerWorkTicket.Status.AWAITING_REVIEW:
            work.submitted_at = now
            work.completion_summary = str(
                request.data.get("completion_summary")
                or work.completion_summary
                or ""
            ).strip()

        source_status = SOURCE_STATUS_MAP.get(requested)
        if source_status:
            work.source_ticket.status = source_status
            source_updates = ["status"]
            if requested == PartnerWorkTicket.Status.SCHEDULED:
                work.source_ticket.scheduled_at = work.scheduled_at
                source_updates.append("scheduled_at")
            elif requested == PartnerWorkTicket.Status.IN_PROGRESS:
                work.source_ticket.started_at = (
                    work.source_ticket.started_at or now
                )
                source_updates.append("started_at")
            elif requested == PartnerWorkTicket.Status.AWAITING_REVIEW:
                work.source_ticket.awaiting_approval_at = now
                source_updates.append("awaiting_approval_at")
            work.source_ticket.save(update_fields=source_updates)

        work.save()
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        work = self.get_object()
        business = self._business()
        if business.id != work.hiring_business_id:
            raise ValidationError(
                {"business": "Only the hiring business can review completion."}
            )
        if work.status != PartnerWorkTicket.Status.AWAITING_REVIEW:
            raise ValidationError(
                {"status": "Work is not awaiting review."}
            )

        decision = str(
            request.data.get("decision") or ""
        ).strip().upper()
        if decision not in {"APPROVE", "RETURN"}:
            raise ValidationError(
                {"decision": "Use APPROVE or RETURN."}
            )

        now = timezone.now()
        work.reviewed_by = request.user
        if decision == "APPROVE":
            work.status = PartnerWorkTicket.Status.COMPLETED
            work.completed_at = now
            work.source_ticket.status = Ticket.Status.COMPLETED
            work.source_ticket.completed_at = now
            work.source_ticket.save(
                update_fields=["status", "completed_at"]
            )
        else:
            work.status = PartnerWorkTicket.Status.IN_PROGRESS
            work.shared_updates = str(
                request.data.get("review_notes")
                or work.shared_updates
                or ""
            ).strip()
            work.source_ticket.status = Ticket.Status.IN_PROGRESS
            work.source_ticket.save(update_fields=["status"])

        work.save()
        return Response(self.get_serializer(work).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        work = self.get_object()
        business = self._business()
        if business.id != work.hiring_business_id:
            raise ValidationError(
                {"business": "Only the hiring business can cancel partner work."}
            )
        if work.status == PartnerWorkTicket.Status.COMPLETED:
            raise ValidationError(
                {"status": "Completed partner work cannot be cancelled."}
            )

        work.status = PartnerWorkTicket.Status.CANCELLED
        work.cancelled_at = timezone.now()
        work.source_ticket.status = Ticket.Status.CANCELLED
        work.source_ticket.cancelled_at = work.cancelled_at
        work.source_ticket.save(
            update_fields=["status", "cancelled_at"]
        )
        work.save()
        return Response(self.get_serializer(work).data)
