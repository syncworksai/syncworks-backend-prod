from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    BusinessResource,
    Ticket,
    TicketDependency,
    TicketRequirement,
    TrackableAsset,
)
from user_accounts.serializers.workflow import (
    TicketDependencySerializer,
    TicketRequirementSerializer,
)
from user_accounts.viewsets.ticket_conversations import (
    _business_context,
    _visible_tickets,
)


DONE_TICKET_STATUSES = {
    Ticket.Status.COMPLETED,
    Ticket.Status.INVOICED,
    Ticket.Status.PAID,
    Ticket.Status.CLOSED,
}

TERMINAL_TICKET_STATUSES = DONE_TICKET_STATUSES | {
    Ticket.Status.CANCELLED,
}

SEVERITY_WEIGHT = {
    TicketRequirement.Severity.CRITICAL: 400,
    TicketRequirement.Severity.HIGH: 300,
    TicketRequirement.Severity.NORMAL: 200,
    TicketRequirement.Severity.LOW: 100,
}


def _ticket_or_404(request, ticket_id):
    ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
    if not ticket:
        raise Http404
    return ticket


def _requirement_payload(requirement):
    return TicketRequirementSerializer(requirement).data


def calculate_next_action(ticket):
    open_requirements = list(
        ticket.requirements.filter(
            status=TicketRequirement.Status.OPEN,
        ).select_related("asset", "resource")
    )
    blocking_requirements = [
        item for item in open_requirements if item.blocks_progress
    ]

    unsatisfied_dependencies = []
    for dependency in ticket.dependencies.select_related("depends_on_ticket"):
        if (
            dependency.is_blocking
            and dependency.depends_on_ticket.status not in DONE_TICKET_STATUSES
        ):
            unsatisfied_dependencies.append(dependency)

    if ticket.status in TERMINAL_TICKET_STATUSES:
        return {
            "state": "DONE",
            "blocked": False,
            "action_code": "NONE",
            "action_label": "No action required",
            "reason": "Ticket is in a terminal state.",
            "requirement": None,
            "dependency": None,
        }

    if blocking_requirements:
        blocking_requirements.sort(
            key=lambda item: (
                -SEVERITY_WEIGHT.get(item.severity, 0),
                item.due_at or timezone.datetime.max.replace(
                    tzinfo=timezone.get_current_timezone()
                ),
                item.id,
            )
        )
        requirement = blocking_requirements[0]
        return {
            "state": "BLOCKED",
            "blocked": True,
            "action_code": f"RESOLVE_{requirement.requirement_type}",
            "action_label": requirement.title,
            "reason": requirement.description or requirement.get_requirement_type_display(),
            "requirement": _requirement_payload(requirement),
            "dependency": None,
        }

    if unsatisfied_dependencies:
        dependency = unsatisfied_dependencies[0]
        return {
            "state": "BLOCKED",
            "blocked": True,
            "action_code": "WAIT_FOR_TICKET",
            "action_label": f"Complete ticket {dependency.depends_on_ticket.ticket_code}",
            "reason": dependency.description or "Another ticket must be completed first.",
            "requirement": None,
            "dependency": TicketDependencySerializer(dependency).data,
        }

    status_actions = {
        Ticket.Status.NEW: ("REVIEW_REQUEST", "Review and assign request"),
        Ticket.Status.ASSIGNED: ("ACCEPT_JOB", "Accept or decline assignment"),
        Ticket.Status.ACCEPTED: ("SCHEDULE_JOB", "Schedule the work"),
        Ticket.Status.SCHEDULED: ("PREPARE_JOB", "Prepare resources and begin travel"),
        Ticket.Status.EN_ROUTE: ("ARRIVE_ON_SITE", "Arrive and check in"),
        Ticket.Status.ON_SITE: ("START_WORK", "Start the work"),
        Ticket.Status.IN_PROGRESS: ("CONTINUE_WORK", "Continue the active work"),
        Ticket.Status.NEEDS_QUOTE: ("CREATE_QUOTE", "Create and send quote"),
        Ticket.Status.QUOTED: ("FOLLOW_UP_QUOTE", "Follow up on quote"),
        Ticket.Status.QUOTE_REJECTED: ("REVISE_QUOTE", "Revise quote or close ticket"),
        Ticket.Status.APPROVED: ("SCHEDULE_JOB", "Schedule approved work"),
        Ticket.Status.AWAITING_APPROVAL: ("FOLLOW_UP_APPROVAL", "Follow up for approval"),
    }
    action_code, action_label = status_actions.get(
        ticket.status,
        ("REVIEW_TICKET", "Review ticket"),
    )
    return {
        "state": "ACTIONABLE",
        "blocked": False,
        "action_code": action_code,
        "action_label": action_label,
        "reason": "No blocking requirements remain.",
        "requirement": None,
        "dependency": None,
    }


def ticket_priority_score(ticket, next_action):
    score = 0
    if next_action["state"] == "ACTIONABLE":
        score += 1000
    elif next_action["state"] == "BLOCKED":
        score += 500

    requirement = next_action.get("requirement")
    if requirement:
        score += SEVERITY_WEIGHT.get(requirement.get("severity"), 0)
        if requirement.get("is_overdue"):
            score += 250

    if ticket.status in {
        Ticket.Status.NEW,
        Ticket.Status.ASSIGNED,
        Ticket.Status.ACCEPTED,
    }:
        score += 150
    elif ticket.status in {
        Ticket.Status.ON_SITE,
        Ticket.Status.IN_PROGRESS,
    }:
        score += 300

    age_hours = max(
        int((timezone.now() - ticket.created_at).total_seconds() // 3600),
        0,
    )
    score += min(age_hours, 240)
    return score


class TicketRequirementListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _ticket_or_404(request, ticket_id)
        requirements = ticket.requirements.select_related(
            "asset",
            "resource",
        )
        return Response({
            "ticket_id": ticket.id,
            "results": TicketRequirementSerializer(
                requirements,
                many=True,
            ).data,
        })

    def post(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _ticket_or_404(request, ticket_id)

        serializer = TicketRequirementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        asset = serializer.validated_data.get("asset")
        if asset and asset.business_id != business.id:
            raise ValidationError(
                {"asset": "Asset does not belong to the active business."}
            )

        resource = serializer.validated_data.get("resource")
        if resource and resource.business_id != business.id:
            raise ValidationError(
                {"resource": "Resource does not belong to the active business."}
            )

        requirement = serializer.save(
            ticket=ticket,
            created_by=request.user,
        )
        return Response(
            TicketRequirementSerializer(requirement).data,
            status=201,
        )


class TicketRequirementDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, requirement_id):
        business, _, _ = _business_context(request)
        requirement = TicketRequirement.objects.select_related(
            "ticket",
            "asset",
            "resource",
        ).filter(
            id=requirement_id,
            ticket__assigned_business=business,
        ).first()
        if not requirement:
            raise Http404

        serializer = TicketRequirementSerializer(
            requirement,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        asset = serializer.validated_data.get("asset")
        if asset and asset.business_id != business.id:
            raise ValidationError(
                {"asset": "Asset does not belong to the active business."}
            )

        resource = serializer.validated_data.get("resource")
        if resource and resource.business_id != business.id:
            raise ValidationError(
                {"resource": "Resource does not belong to the active business."}
            )

        new_status = serializer.validated_data.get(
            "status",
            requirement.status,
        )
        save_kwargs = {}
        if (
            new_status in {
                TicketRequirement.Status.SATISFIED,
                TicketRequirement.Status.WAIVED,
            }
            and requirement.status == TicketRequirement.Status.OPEN
        ):
            save_kwargs["satisfied_at"] = timezone.now()
            save_kwargs["satisfied_by"] = request.user
        elif new_status == TicketRequirement.Status.OPEN:
            save_kwargs["satisfied_at"] = None
            save_kwargs["satisfied_by"] = None

        requirement = serializer.save(**save_kwargs)
        return Response(TicketRequirementSerializer(requirement).data)


class TicketDependencyListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _ticket_or_404(request, ticket_id)
        dependencies = ticket.dependencies.select_related(
            "depends_on_ticket",
        )
        return Response({
            "ticket_id": ticket.id,
            "results": TicketDependencySerializer(
                dependencies,
                many=True,
            ).data,
        })

    def post(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _ticket_or_404(request, ticket_id)
        depends_on_id = (request.data or {}).get("depends_on_ticket")

        depends_on = _visible_tickets(
            request,
            "BUSINESS",
        ).filter(id=depends_on_id).first()
        if not depends_on:
            raise ValidationError(
                {"depends_on_ticket": "Dependency ticket was not found."}
            )
        if depends_on.id == ticket.id:
            raise ValidationError(
                {"depends_on_ticket": "A ticket cannot depend on itself."}
            )
        if depends_on.assigned_business_id != business.id:
            raise ValidationError(
                {"depends_on_ticket": "Dependency must belong to the active business."}
            )

        serializer = TicketDependencySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                dependency = serializer.save(
                    ticket=ticket,
                    created_by=request.user,
                )
        except IntegrityError:
            raise ValidationError(
                {"depends_on_ticket": "This dependency already exists."}
            )

        return Response(
            TicketDependencySerializer(dependency).data,
            status=201,
        )


class TicketNextActionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _ticket_or_404(request, ticket_id)
        return Response({
            "ticket_id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "status": ticket.status,
            "next_action": calculate_next_action(ticket),
        })


class BusinessPriorityQueueAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _, _ = _business_context(request)
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)

        tickets = list(
            _visible_tickets(request, "BUSINESS")
            .filter(assigned_business=business, archived_at__isnull=True)
            .exclude(status__in=TERMINAL_TICKET_STATUSES)
            .prefetch_related(
                Prefetch(
                    "requirements",
                    queryset=TicketRequirement.objects.select_related(
                        "asset",
                        "resource",
                    ),
                ),
                Prefetch(
                    "dependencies",
                    queryset=TicketDependency.objects.select_related(
                        "depends_on_ticket",
                    ),
                ),
            )[:500]
        )

        items = []
        for ticket in tickets:
            next_action = calculate_next_action(ticket)
            items.append({
                "ticket_id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "status": ticket.status,
                "created_at": ticket.created_at,
                "priority_score": ticket_priority_score(
                    ticket,
                    next_action,
                ),
                "next_action": next_action,
            })

        items.sort(
            key=lambda item: (
                -item["priority_score"],
                item["created_at"],
                item["ticket_id"],
            )
        )
        return Response({
            "business_id": business.id,
            "count": len(items[:limit]),
            "results": items[:limit],
        })
