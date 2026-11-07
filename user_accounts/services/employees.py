from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from typing import Optional, Dict, Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from rest_framework.authtoken.models import Token

from user_accounts.models import InviteCode
from user_accounts.models.business import Business, BusinessMember, BusinessMemberRole

User = get_user_model()


@dataclass
class InviteEmployeeResult:
    invite: InviteCode
    user: Optional[User] = None
    member: Optional[BusinessMember] = None


def _coerce_employee_role(raw_role: str) -> str:
    raw_role = (raw_role or "").strip().upper()
    valid_roles = [choice[0] for choice in BusinessMemberRole.choices]
    if raw_role not in valid_roles:
        raise ValueError("Invalid seat_role")
    return raw_role


def _set_employee_role(user: User) -> None:
    changed = False

    if getattr(user, "role", None) != "EMPLOYEE":
        user.role = "EMPLOYEE"
        changed = True

    if getattr(user, "is_staff", False):
        user.is_staff = False
        changed = True

    if getattr(user, "is_superuser", False):
        user.is_superuser = False
        changed = True

    if changed:
        update_fields = ["role", "is_staff", "is_superuser"]
        if not getattr(user, "username", ""):
            user.username = user.email
            update_fields.append("username")
        user.save(update_fields=update_fields)


def _apply_permissions_to_member(member: BusinessMember, permissions: Optional[Dict[str, bool]]) -> None:
    if not permissions:
        return

    allowed = {
        "can_manage_team",
        "can_manage_settings",
        "can_view_financials",
        "can_manage_invoices",
        "can_create_tickets",
        "can_assign_tickets",
        "can_close_tickets",
        "can_manage_schedule",
        "can_manage_categories",
        "can_manage_properties",
        "can_manage_connections",
    }

    changed = []
    for key, value in permissions.items():
        if key in allowed and hasattr(member, key):
            setattr(member, key, bool(value))
            changed.append(key)

    if changed:
        member.save(update_fields=changed)


def _copy_invite_permissions_to_member(invite: InviteCode, member: BusinessMember) -> None:
    mapping = [
        "can_manage_team",
        "can_manage_settings",
        "can_view_financials",
        "can_manage_invoices",
        "can_create_tickets",
        "can_assign_tickets",
        "can_close_tickets",
        "can_manage_schedule",
        "can_manage_categories",
        "can_manage_properties",
        "can_manage_connections",
    ]

    changed = []
    for key in mapping:
        if hasattr(member, key) and hasattr(invite, key):
            value = bool(getattr(invite, key, False))
            setattr(member, key, value)
            changed.append(key)

    if changed:
        member.save(update_fields=changed)


@transaction.atomic
def invite_employee(
    *,
    business: Business,
    invited_by: User,
    email: str,
    seat_role: str,
    permissions: Optional[Dict[str, bool]] = None,
) -> InviteEmployeeResult:
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email is required")

    seat_role = _coerce_employee_role(seat_role)

    invite_fields: Dict[str, Any] = {
        "business": business,
        "created_by": invited_by,
        "email": email,
        "role": seat_role,
    }

    allowed_invite_perm_fields = [
        "can_manage_team",
        "can_manage_settings",
        "can_view_financials",
        "can_manage_invoices",
        "can_create_tickets",
        "can_assign_tickets",
        "can_close_tickets",
        "can_manage_schedule",
        "can_manage_categories",
        "can_manage_properties",
        "can_manage_connections",
    ]

    for key in allowed_invite_perm_fields:
        invite_fields[key] = bool((permissions or {}).get(key, False))

    # No employee membership is granted until the invited address signs in
    # and explicitly accepts. Do not create users or change account roles here.
    invite = InviteCode.objects.create(**invite_fields)
    site = getattr(settings, "SYNCWORKS_PUBLIC_URL", "https://www.syncworksapp.com").rstrip("/")
    link = f"{site}/employee/invite?code={quote(invite.code, safe='')}"
    sender = settings.DEFAULT_FROM_EMAIL
    if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        raise RuntimeError("Email delivery is not configured. Set up the SyncWorks SMTP email backend before sending invites.")
    send_mail(
        subject=f"{business.name} invited you to join their team on SyncWorks",
        message=(
            f"You have been invited by {business.name} to join their team on SyncWorks "
            f"as {seat_role.replace('_', ' ').title()}.\\n\\n"
            f"Accept your invitation: {link}\\n\\n"
            "Sign in with your existing SyncWorks account or create one first. "
            "Your existing login and password will not change. "
            "If you did not expect this invitation, ignore this email.\\n"
        ),
        from_email=sender,
        recipient_list=[email],
        fail_silently=False,
    )
    return InviteEmployeeResult(invite=invite)


@transaction.atomic
def accept_employee_invite(
    *,
    code: str,
    accepting_user: User,
) -> Dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise ValueError("code is required")

    invite = InviteCode.objects.select_for_update().get(code=code)

    if invite.used_at is not None:
        raise ValueError("Invite already used")
    if invite.is_expired:
        raise ValueError("Invite expired")

    email = (invite.email or "").strip().lower()
    if not email or email != (accepting_user.email or "").strip().lower():
        raise ValueError("Sign in with the email address that received the invitation.")
    business = invite.business
    if not business:
        raise ValueError("Invite is missing a business.")

    # Existing Personal, Business, PM, and platform roles and credentials
    # must stay untouched. Only a scoped business membership is added.
    member, _ = BusinessMember.objects.get_or_create(
        business=business,
        user=accepting_user,
        defaults={"role": invite.role or BusinessMemberRole.TECHNICIAN, "is_active": True},
    )
    member_fields = []
    if member.role != invite.role:
        member.role = invite.role
        member_fields.append("role")
    if not member.is_active:
        member.is_active = True
        member_fields.append("is_active")
    if member_fields:
        member.save(update_fields=member_fields)

    _copy_invite_permissions_to_member(invite, member)
    invite.used_at = timezone.now()
    if hasattr(invite, "accepted_by"):
        invite.accepted_by = accepting_user
        invite.save(update_fields=["used_at", "accepted_by"])
    else:
        invite.save(update_fields=["used_at"])

    token, _ = Token.objects.get_or_create(user=accepting_user)
    return {
        "token": token.key,
        "user": {
            "id": accepting_user.id,
            "email": accepting_user.email,
            "role": getattr(accepting_user, "role", None),
            "first_name": accepting_user.first_name,
            "last_name": accepting_user.last_name,
        },
        "business_id": member.business_id,
        "business_member_id": member.id,
    }

@transaction.atomic
def terminate_member(*, member: BusinessMember, terminated_by: User) -> BusinessMember:
    member.is_active = False
    if hasattr(member, "terminated_at"):
        member.terminated_at = timezone.now()
        member.save(update_fields=["is_active", "terminated_at"])
    else:
        member.save(update_fields=["is_active"])
    return member