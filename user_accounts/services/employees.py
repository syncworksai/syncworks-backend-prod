from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from rest_framework.authtoken.models import Token

from user_accounts.models.business import Business, BusinessMember, BusinessMemberRole
from user_accounts.models.connections import InviteCode, InviteKind

User = get_user_model()


@dataclass
class InviteEmployeeResult:
    invite: InviteCode
    user: User
    member: BusinessMember


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

    valid_roles = [c[0] for c in BusinessMemberRole.choices]
    if seat_role not in valid_roles:
        raise ValueError("Invalid seat_role")

    user, created = User.objects.get_or_create(
        email=email,
        defaults={"role": "EMPLOYEE"},
    )
    if not created and getattr(user, "role", None) != "EMPLOYEE":
        user.role = "EMPLOYEE"
        user.save(update_fields=["role"])

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])

    member, _ = BusinessMember.objects.get_or_create(
        business=business,
        user=user,
        defaults={"role": seat_role, "is_active": True},
    )

    if member.terminated_at is not None or not member.is_active:
        member.is_active = True
        member.terminated_at = None
        member.role = seat_role
        member.save(update_fields=["is_active", "terminated_at", "role"])

    if permissions:
        member.apply_permissions(permissions)
        member.save()

    invite = InviteCode.objects.create_employee_invite(
        business=business,
        invited_by=invited_by,
        email=email,
        member=member,
    )

    return InviteEmployeeResult(invite=invite, user=user, member=member)


@transaction.atomic
def accept_employee_invite(
    *,
    code: str,
    first_name: str,
    last_name: str,
    password: str,
) -> Dict[str, Any]:
    invite = InviteCode.objects.select_for_update().get(code=code, kind=InviteKind.EMPLOYEE)
    if invite.used_at is not None:
        raise ValueError("Invite already used")
    if invite.is_expired:
        raise ValueError("Invite expired")

    payload = invite.payload or {}
    email = (payload.get("email") or "").strip().lower()
    member_id = payload.get("member_id")

    if not email or not member_id:
        raise ValueError("Invite payload invalid")

    user = User.objects.get(email=email)
    member = BusinessMember.objects.select_for_update().get(id=member_id, user=user)

    user.first_name = first_name or ""
    user.last_name = last_name or ""
    validate_password(password, user=user)
    user.set_password(password)
    user.role = "EMPLOYEE"
    user.save(update_fields=["first_name", "last_name", "password", "role"])

    member.is_active = True
    member.terminated_at = None
    member.save(update_fields=["is_active", "terminated_at"])

    invite.used_at = timezone.now()
    invite.used_by = user
    invite.save(update_fields=["used_at", "used_by"])

    token, _ = Token.objects.get_or_create(user=user)

    return {
        "token": token.key,
        "user": {"id": user.id, "email": user.email, "role": getattr(user, "role", None)},
        "business_id": member.business_id,
        "business_member_id": member.id,
    }


@transaction.atomic
def terminate_member(*, member: BusinessMember, terminated_by: User) -> BusinessMember:
    member.is_active = False
    member.terminated_at = timezone.now()
    member.save(update_fields=["is_active", "terminated_at"])
    return member
