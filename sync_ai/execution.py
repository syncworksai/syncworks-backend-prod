from __future__ import annotations

from django.db import transaction

from user_accounts.models import AuditLog, Ticket, TicketMessage

from .context import WorkspaceContext


def resolve_ticket_for_reply(
    *,
    user,
    context: WorkspaceContext,
    ticket_id: int,
) -> Ticket:
    ticket = (
        Ticket.objects.select_related(
            "customer",
            "assigned_business",
            "payer_business",
        )
        .filter(pk=ticket_id)
        .first()
    )
    if ticket is None:
        raise LookupError("Ticket not found.")

    if context.workspace == "personal":
        if ticket.customer_id != user.id:
            raise PermissionError("You do not have access to this ticket.")
        return ticket

    business_id = context.business.id if context.business else None
    if business_id is None:
        raise PermissionError("An active Business workspace is required.")

    allowed_business_ids = {
        ticket.assigned_business_id,
        ticket.payer_business_id,
    }
    if business_id not in allowed_business_ids:
        raise PermissionError("This ticket does not belong to the active Business.")

    return ticket


@transaction.atomic
def execute_ticket_reply(
    *,
    user,
    context: WorkspaceContext,
    ticket_id: int,
    body: str,
) -> TicketMessage:
    ticket = resolve_ticket_for_reply(
        user=user,
        context=context,
        ticket_id=ticket_id,
    )

    message = TicketMessage.objects.create(
        ticket=ticket,
        sender=user,
        body=body,
        type=TicketMessage.MessageType.USER,
    )

    AuditLog.objects.create(
        actor=user,
        action="sync_ai.ticket_reply_executed",
        metadata={
            "feature": "sync_ticket_reply",
            "workspace": context.workspace,
            "role": context.role,
            "business_id": str(context.business.id) if context.business else "",
            "ticket_id": str(ticket.id),
            "ticket_message_id": str(message.id),
            "body_length": len(body),
            "confirmed": True,
            "executed": True,
        },
    )

    return message
