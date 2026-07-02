from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import BusinessMember, BusinessProject, Ticket
from user_accounts.serializers.projects import BusinessProjectSerializer, ProjectChildTicketSerializer, project_rollup
from user_accounts.viewsets.ticket_conversations import _business_context


class BusinessProjectViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        business, _, _ = _business_context(self.request)
        return BusinessProject.objects.filter(business=business).select_related(
            "business", "business_customer", "primary_ticket", "created_by", "updated_by"
        ).prefetch_related("tickets__category", "tickets__assigned_member", "tickets__business_customer")

    def perform_create(self, serializer):
        business, _, _ = _business_context(self.request)
        customer = serializer.validated_data.get("business_customer")
        if customer and customer.business_id != business.id:
            raise ValidationError({"business_customer": "Customer belongs to another business."})
        serializer.save(business=business, created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        business, _, _ = _business_context(self.request)
        customer = serializer.validated_data.get("business_customer")
        if customer and customer.business_id != business.id:
            raise ValidationError({"business_customer": "Customer belongs to another business."})
        old_status = serializer.instance.status
        project = serializer.save(updated_by=self.request.user)
        if old_status != BusinessProject.Status.COMPLETED and project.status == BusinessProject.Status.COMPLETED and not project.completed_at:
            project.completed_at = timezone.now()
            project.save(update_fields=["completed_at"])

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        project = self.get_object()
        return Response({"project_id": project.id, "title": project.title, "status": project.status,
                         "billing_mode": project.billing_mode, "progress_mode": project.progress_mode,
                         "customer_status_note": project.customer_status_note, **project_rollup(project)})

    @action(detail=True, methods=["post"], url_path="children")
    def create_child(self, request, pk=None):
        project = self.get_object()
        business, _, _ = _business_context(request)
        serializer = ProjectChildTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = data.get("assigned_member")
        if member and not BusinessMember.objects.filter(business=business, user=member, is_active=True).exists():
            raise ValidationError({"assigned_member": "User is not an active business member."})
        parent = data.get("parent_ticket")
        if parent and parent.assigned_business_id != business.id:
            raise ValidationError({"parent_ticket": "Parent ticket belongs to another business."})
        customer = project.business_customer
        with transaction.atomic():
            ticket = Ticket.objects.create(
                customer=request.user, business_customer=customer, assigned_business=business,
                project=project, parent_ticket=parent, category=data.get("category"), assigned_member=member,
                is_marketplace=False, is_imported=False, exclude_from_operational_kpis=False,
                work_title=data.get("work_title") or project.title, work_scope=data.get("work_scope") or "",
                status=data.get("status") or Ticket.Status.NEW,
                service_address=data.get("service_address") or (customer.service_address if customer else ""),
                service_zip=(data.get("service_zip") or (customer.service_zip if customer else ""))[:10],
                scheduled_at=data.get("scheduled_at"), progress_weight=data.get("progress_weight") or 1,
                customer_visible=data.get("customer_visible", True),
                customer_status_label=data.get("customer_status_label") or "",
                projected_customer_amount_cents=data.get("projected_customer_amount_cents") or 0,
                projected_cost_cents=data.get("projected_cost_cents") or 0,
                actual_customer_amount_cents=data.get("actual_customer_amount_cents") or 0,
                actual_cost_cents=data.get("actual_cost_cents") or 0,
            )
            if not project.primary_ticket_id:
                project.primary_ticket = ticket
                project.status = BusinessProject.Status.ACTIVE
                project.updated_by = request.user
                project.save(update_fields=["primary_ticket", "status", "updated_by", "updated_at"])
        return Response(ProjectChildTicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="attach-ticket")
    def attach_ticket(self, request, pk=None):
        project = self.get_object()
        business, _, _ = _business_context(request)
        try:
            ticket_id = int(request.data.get("ticket_id"))
        except (TypeError, ValueError):
            raise ValidationError({"ticket_id": "Use a numeric ticket ID."})
        ticket = Ticket.objects.filter(id=ticket_id, assigned_business=business).first()
        if not ticket:
            raise ValidationError({"ticket_id": "Ticket was not found."})
        clone = str(request.data.get("clone_as_native") or "").strip().lower() in {"1", "true", "yes"}
        if ticket.is_imported and not clone:
            raise ValidationError({"clone_as_native": "Imported history must be cloned. Set clone_as_native=true."})
        if clone:
            target = Ticket.objects.create(
                customer=request.user, business_customer=ticket.business_customer or project.business_customer,
                assigned_business=business, project=project, parent_ticket=ticket, category=ticket.category,
                is_marketplace=False, is_imported=False, exclude_from_operational_kpis=False,
                work_title=str(request.data.get("work_title") or "").strip() or ticket.work_title or project.title,
                work_scope=str(request.data.get("work_scope") or "").strip() or ticket.work_scope,
                service_address=ticket.service_address, service_zip=ticket.service_zip, status=Ticket.Status.NEW,
                payment_method=ticket.payment_method,
                projected_customer_amount_cents=ticket.total_amount_cents or ticket.projected_customer_amount_cents or 0,
                progress_weight=int(request.data.get("progress_weight") or 1), customer_visible=True,
            )
        else:
            ticket.project = project
            ticket.business_customer = ticket.business_customer or project.business_customer
            ticket.save(update_fields=["project", "business_customer"])
            target = ticket
        if not project.primary_ticket_id:
            project.primary_ticket = target
            project.status = BusinessProject.Status.ACTIVE
            project.updated_by = request.user
            project.save(update_fields=["primary_ticket", "status", "updated_by", "updated_at"])
        return Response(ProjectChildTicketSerializer(target).data, status=status.HTTP_201_CREATED if clone else status.HTTP_200_OK)
