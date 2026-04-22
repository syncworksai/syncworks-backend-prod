from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from user_accounts.models.tickets import Ticket
from user_accounts.models.business import BusinessMember


# =========================================================
# 🔐 PERMISSION HELPERS (CLEAN + ROLE-BASED)
# =========================================================

def _is_owner_manager_dispatch(member: BusinessMember | None) -> bool:
    if not member:
        return False
    return (
        member.role in ["OWNER", "MANAGER", "DISPATCH"]
        or getattr(member, "can_manage_schedule", False)
    )


def _is_assigned_tech(member: BusinessMember | None, ticket: Ticket) -> bool:
    if not member or not ticket:
        return False
    return ticket.assigned_member_id == member.user_id


def _can_complete(member: BusinessMember | None, ticket: Ticket) -> bool:
    if not member:
        return False
    return (
        _is_assigned_tech(member, ticket)
        or getattr(member, "can_close_tickets", False)
    )


# =========================================================
# 🧠 STATUS TRANSITIONS (REAL WORKFLOW ENGINE)
# =========================================================

def schedule_ticket(ticket: Ticket, member: BusinessMember):
    if not _is_owner_manager_dispatch(member):
        raise PermissionDenied("You do not have permission to schedule this ticket.")

    ticket.status = Ticket.Status.SCHEDULED
    ticket.scheduled_at = timezone.now()
    ticket.save(update_fields=["status", "scheduled_at"])


def mark_en_route(ticket: Ticket, member: BusinessMember):
    if not _is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can mark En Route.")

    ticket.status = Ticket.Status.EN_ROUTE
    ticket.en_route_at = timezone.now()
    ticket.save(update_fields=["status", "en_route_at"])


def mark_on_site(ticket: Ticket, member: BusinessMember):
    if not _is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can mark On Site.")

    ticket.status = Ticket.Status.ON_SITE
    ticket.on_site_at = timezone.now()
    ticket.save(update_fields=["status", "on_site_at"])


def start_work(ticket: Ticket, member: BusinessMember):
    if not _is_assigned_tech(member, ticket):
        raise PermissionDenied("Only the assigned technician can start work.")

    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.started_at = timezone.now()
    ticket.save(update_fields=["status", "started_at"])


def complete_ticket(ticket: Ticket, member: BusinessMember):
    if not _can_complete(member, ticket):
        raise PermissionDenied("You do not have permission to complete this ticket.")

    ticket.status = Ticket.Status.COMPLETED
    ticket.completed_at = timezone.now()
    ticket.save(update_fields=["status", "completed_at"])