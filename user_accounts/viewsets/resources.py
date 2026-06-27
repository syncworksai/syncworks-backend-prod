from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    BusinessResource,
    ResourceAssignment,
    ResourceMovement,
    TrackableAsset,
)
from user_accounts.serializers.resources import (
    BusinessResourceSerializer,
    ResourceAssignmentSerializer,
    ResourceMovementSerializer,
)
from user_accounts.viewsets.ticket_conversations import _business_context, _visible_tickets


OPEN_ASSIGNMENT_STATUSES = [
    ResourceAssignment.Status.PLANNED,
    ResourceAssignment.Status.ACTIVE,
]


def _resource_queryset(request):
    business, _, _ = _business_context(request)
    queryset = BusinessResource.objects.filter(business=business).annotate(
        open_assignment_count=Count(
            "assignments",
            filter=Q(assignments__status__in=OPEN_ASSIGNMENT_STATUSES),
        )
    )
    return business, queryset


def _resource_or_404(request, resource_id):
    business, queryset = _resource_queryset(request)
    resource = queryset.filter(id=resource_id).first()
    if not resource:
        raise Http404
    return business, resource


class ResourceListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, queryset = _resource_queryset(request)
        resource_type = str(
            request.query_params.get("resource_type") or ""
        ).strip().upper()
        status = str(request.query_params.get("status") or "").strip().upper()
        available_only = str(
            request.query_params.get("available_only") or ""
        ).lower() in {"1", "true", "yes"}
        query = str(request.query_params.get("q") or "").strip()

        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        if status:
            queryset = queryset.filter(status=status)
        if available_only:
            queryset = queryset.filter(
                is_active=True,
                status__in=[
                    BusinessResource.Status.AVAILABLE,
                    BusinessResource.Status.RESERVED,
                ],
            )
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | Q(location__icontains=query)
            )

        results = list(queryset[:300])
        if available_only:
            results = [
                item
                for item in results
                if item.open_assignment_count < item.capacity
            ]

        return Response({
            "business_id": business.id,
            "results": BusinessResourceSerializer(results, many=True).data,
        })

    def post(self, request):
        business, _, _ = _business_context(request)
        serializer = BusinessResourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            resource = serializer.save(
                business=business,
                created_by=request.user,
            )
        except IntegrityError:
            raise ValidationError(
                {"name": "A resource with this name already exists in the business."}
            )

        resource.open_assignment_count = 0
        return Response(BusinessResourceSerializer(resource).data, status=201)


class ResourceDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, resource_id):
        _, resource = _resource_or_404(request, resource_id)
        return Response(BusinessResourceSerializer(resource).data)

    def patch(self, request, resource_id):
        _, resource = _resource_or_404(request, resource_id)
        serializer = BusinessResourceSerializer(
            resource,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        try:
            resource = serializer.save()
        except IntegrityError:
            raise ValidationError(
                {"name": "A resource with this name already exists in the business."}
            )
        resource.open_assignment_count = ResourceAssignment.objects.filter(
            resource=resource,
            status__in=OPEN_ASSIGNMENT_STATUSES,
        ).count()
        return Response(BusinessResourceSerializer(resource).data)


class TicketResourceAssignmentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
        if not ticket:
            raise Http404

        assignments = ResourceAssignment.objects.filter(
            ticket=ticket
        ).select_related("resource")
        return Response({
            "ticket_id": ticket.id,
            "results": ResourceAssignmentSerializer(assignments, many=True).data,
        })

    def post(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
        if not ticket:
            raise Http404

        resource_id = (request.data or {}).get("resource")
        resource = BusinessResource.objects.filter(
            id=resource_id,
            business=business,
            is_active=True,
        ).first()
        if not resource:
            raise ValidationError(
                {"resource": "Resource was not found in the active business."}
            )

        if resource.status in {
            BusinessResource.Status.UNAVAILABLE,
            BusinessResource.Status.MAINTENANCE,
            BusinessResource.Status.INACTIVE,
        }:
            raise ValidationError(
                {"resource": "This resource is not currently assignable."}
            )

        open_count = ResourceAssignment.objects.filter(
            resource=resource,
            status__in=OPEN_ASSIGNMENT_STATUSES,
        ).count()
        if open_count >= resource.capacity:
            raise ValidationError(
                {"resource": "This resource has no available capacity."}
            )

        serializer = ResourceAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                assignment = serializer.save(
                    resource=resource,
                    ticket=ticket,
                    assigned_by=request.user,
                )
                if assignment.status == ResourceAssignment.Status.ACTIVE:
                    BusinessResource.objects.filter(id=resource.id).update(
                        status=BusinessResource.Status.OCCUPIED
                    )
        except IntegrityError:
            raise ValidationError(
                {"resource": "This ticket already has an open assignment to the resource."}
            )

        return Response(
            ResourceAssignmentSerializer(assignment).data,
            status=201,
        )


class ResourceAssignmentDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, assignment_id):
        business, _, _ = _business_context(request)
        assignment = ResourceAssignment.objects.select_related(
            "resource",
            "ticket",
        ).filter(
            id=assignment_id,
            resource__business=business,
        ).first()
        if not assignment:
            raise Http404

        serializer = ResourceAssignmentSerializer(
            assignment,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()

        if assignment.status == ResourceAssignment.Status.ACTIVE:
            BusinessResource.objects.filter(id=assignment.resource_id).update(
                status=BusinessResource.Status.OCCUPIED
            )
        elif assignment.status in {
            ResourceAssignment.Status.COMPLETED,
            ResourceAssignment.Status.CANCELLED,
        }:
            other_open = ResourceAssignment.objects.filter(
                resource_id=assignment.resource_id,
                status__in=OPEN_ASSIGNMENT_STATUSES,
            ).exclude(id=assignment.id).exists()
            if not other_open:
                BusinessResource.objects.filter(id=assignment.resource_id).update(
                    status=BusinessResource.Status.AVAILABLE
                )

        return Response(ResourceAssignmentSerializer(assignment).data)


class ResourceMovementAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, resource_id):
        _, resource = _resource_or_404(request, resource_id)
        movements = ResourceMovement.objects.filter(
            resource=resource
        ).select_related("asset", "ticket")[:200]
        return Response({
            "resource_id": resource.id,
            "results": ResourceMovementSerializer(movements, many=True).data,
        })

    def post(self, request, resource_id):
        business, resource = _resource_or_404(request, resource_id)
        asset_id = (request.data or {}).get("asset")
        ticket_id = (request.data or {}).get("ticket")
        to_location = str((request.data or {}).get("to_location") or "").strip()

        if not to_location:
            raise ValidationError({"to_location": "Destination is required."})

        asset = None
        if asset_id:
            asset = TrackableAsset.objects.filter(
                id=asset_id,
                business=business,
            ).first()
            if not asset:
                raise ValidationError(
                    {"asset": "Asset was not found in the active business."}
                )

        ticket = None
        if ticket_id:
            ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
            if not ticket:
                raise ValidationError(
                    {"ticket": "Ticket was not found in the active business."}
                )

        movement = ResourceMovement.objects.create(
            resource=resource,
            asset=asset,
            ticket=ticket,
            from_location=resource.location,
            to_location=to_location,
            reason=str((request.data or {}).get("reason") or "").strip(),
            moved_by=request.user,
        )
        resource.location = to_location
        resource.save(update_fields=["location", "updated_at"])

        return Response(ResourceMovementSerializer(movement).data, status=201)
