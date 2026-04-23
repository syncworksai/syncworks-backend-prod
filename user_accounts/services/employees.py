from __future__ import annotations

from dataclasses import dataclass
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
    user: User
    member: BusinessMember


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

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "role": "EMPLOYEE",
            "username": email,
        },
    )

    if created and not getattr(user, "username", ""):
        user.username = email
        user.save(update_fields=["username"])

    _set_employee_role(user)

    member, _ = BusinessMember.objects.get_or_create(
        business=business,
        user=user,
        defaults={"role": seat_role, "is_active": True},
    )

    member_changed = []
    if getattr(member, "role", None) != seat_role:
        member.role = seat_role
        member_changed.append("role")

    if not getattr(member, "is_active", False):
        member.is_active = True
        member_changed.append("is_active")

    if hasattr(member, "terminated_at") and getattr(member, "terminated_at", None) is not None:
        member.terminated_at = None
        member_changed.append("terminated_at")

    if member_changed:
        member.save(update_fields=member_changed)

    _apply_permissions_to_member(member, permissions)

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

    invite = InviteCode.objects.create(**invite_fields)

    return InviteEmployeeResult(invite=invite, user=user, member=member)


@transaction.atomic
def accept_employee_invite(
    *,
    code: str,
    first_name: str,
    last_name: str,
    password: str,
) -> Dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise ValueError("code is required")

    invite = InviteCode.objects.select_for_update().get(code=code)

    if getattr(invite, "used_at", None) is not None:
        raise ValueError("Invite already used")

    if getattr(invite, "is_expired", False):
        raise ValueError("Invite expired")

    email = (getattr(invite, "email", "") or "").strip().lower()
    business = getattr(invite, "business", None)
    seat_role = getattr(invite, "role", None)

    if not email or not business:
        raise ValueError("Invite is missing required onboarding data")

    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "role": "EMPLOYEE",
            "username": email,
        },
    )

    validate_password(password, user=user)

    update_fields = []
    if first_name is not None:
        user.first_name = first_name or ""
        update_fields.append("first_name")
    if last_name is not None:
        user.last_name = last_name or ""
        update_fields.append("last_name")

    user.set_password(password)
    user.role = "EMPLOYEE"
    update_fields.extend(["password", "role"])

    if not getattr(user, "username", ""):
        user.username = email
        update_fields.append("username")

    user.save(update_fields=list(dict.fromkeys(update_fields)))

    member, _ = BusinessMember.objects.get_or_create(
        business=business,
        user=user,
        defaults={
            "role": seat_role or BusinessMemberRole.TECHNICIAN,
            "is_active": True,
        },
    )

    member_fields = []
    if seat_role and getattr(member, "role", None) != seat_role:
        member.role = seat_role
        member_fields.append("role")

    if not getattr(member, "is_active", False):
        member.is_active = True
        member_fields.append("is_active")

    if hasattr(member, "terminated_at") and getattr(member, "terminated_at", None) is not None:
        member.terminated_at = None
        member_fields.append("terminated_at")

    if member_fields:
        member.save(update_fields=member_fields)

    _copy_invite_permissions_to_member(invite, member)

    invite.used_at = timezone.now()
    if hasattr(invite, "accepted_by"):
        invite.accepted_by = user
        invite.save(update_fields=["used_at", "accepted_by"])
    else:
        invite.save(update_fields=["used_at"])

    token, _ = Token.objects.get_or_create(user=user)

    return {
        "token": token.key,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": getattr(user, "role", None),
            "first_name": user.first_name,
            "last_name": user.last_name,
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