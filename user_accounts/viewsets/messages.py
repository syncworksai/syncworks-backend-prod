from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status

from user_accounts.models import TicketMessage, TicketAttachment, Ticket, Roles
from user_accounts.serializers import TicketMessageSerializer, TicketAttachmentSerializer
from user_accounts.services.permissions import get_active_membership


class TicketMessageViewSet(viewsets.ModelViewSet):
    serializer_class = TicketMessageSerializer

    def get_queryset(self):
        ticket_id = self.request.query_params.get("ticket")
        qs = TicketMessage.objects.all().order_by("created_at")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def create(self, request, *args, **kwargs):
        ser = TicketMessageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        ticket_id = ser.validated_data["ticket"].id
        ticket = Ticket.objects.get(id=ticket_id)
        msg_type = ser.validated_data["type"]

        # Customer cannot post INTERNAL
        if request.user.role == Roles.CUSTOMER and msg_type == TicketMessage.MessageType.INTERNAL:
            return Response({"detail": "Customer cannot post INTERNAL messages."}, status=403)

        # Employee INTERNAL requires permission
        if request.user.role == Roles.EMPLOYEE and msg_type == TicketMessage.MessageType.INTERNAL:
            if not ticket.assigned_business_id:
                return Response({"detail": "Ticket not assigned to a business."}, status=400)
            mem = get_active_membership(request.user, ticket.assigned_business_id)
            if not mem or not mem.can_post_internal_messages:
                return Response({"detail": "Not allowed to post INTERNAL."}, status=403)

        obj = TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            body=ser.validated_data["body"],
            type=msg_type,
        )
        return Response(TicketMessageSerializer(obj).data, status=201)

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    serializer_class = TicketAttachmentSerializer

    def get_queryset(self):
        ticket_id = self.request.query_params.get("ticket")
        qs = TicketAttachment.objects.all().order_by("created_at")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)
