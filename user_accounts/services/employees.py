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
    if getattr(user, "role", None) != "EMPLOYEE":
        user.role = "EMPLOYEE"
        user.save(update_fields=["role"])

    changed = False
    if getattr(user, "is_staff", False):
        user.is_staff = False
        changed = True
    if getattr(user, "is_superuser", False):
        user.is_superuser = False
        changed = True
    if changed:
        user.save(update_fields=["is_staff", "is_superuser"])


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

    changed_fields = []

    if getattr(member, "role", None) != seat_role:
        member.role = seat_role
        changed_fields.append("role")

    if getattr(member, "terminated_at", None) is not None:
        member.terminated_at = None
        changed_fields.append("terminated_at")

    if not getattr(member, "is_active", False):
        member.is_active = True
        changed_fields.append("is_active")

    if changed_fields:
        member.save(update_fields=changed_fields)

    if permissions:
        if hasattr(member, "apply_permissions"):
            member.apply_permissions(permissions)
            member.save()
        else:
            for key, value in permissions.items():
                if hasattr(member, key):
                    setattr(member, key, bool(value))
            member.save()

    # Project-specific helper if it exists
    if hasattr(InviteCode.objects, "create_employee_invite"):
        invite = InviteCode.objects.create_employee_invite(
            business=business,
            invited_by=invited_by,
            email=email,
            member=member,
        )
    else:
        payload = {
            "email": email,
            "member_id": member.id,
            "business_id": business.id,
            "role": seat_role,
        }

        create_kwargs: Dict[str, Any] = {
            "payload": payload,
        }

        # Common optional fields across invite models
        if hasattr(InviteCode, "business_id"):
            create_kwargs["business"] = business
        if hasattr(InviteCode, "created_by_id"):
            create_kwargs["created_by"] = invited_by
        if hasattr(InviteCode, "invited_by_id"):
            create_kwargs["invited_by"] = invited_by
        if hasattr(InviteCode, "email"):
            create_kwargs["email"] = email
        if hasattr(InviteCode, "kind"):
            create_kwargs["kind"] = "EMPLOYEE"
        if hasattr(InviteCode, "member_id"):
            create_kwargs["member"] = member

        invite = InviteCode.objects.create(**create_kwargs)

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

    invite_kind = str(getattr(invite, "kind", "") or "").upper()
    if invite_kind and invite_kind != "EMPLOYEE":
        raise ValueError("Invite is not an employee invite")

    used_at = getattr(invite, "used_at", None)
    if used_at is not None:
        raise ValueError("Invite already used")

    is_expired = getattr(invite, "is_expired", False)
    if is_expired:
        raise ValueError("Invite expired")

    payload = getattr(invite, "payload", None) or {}
    email = (payload.get("email") or getattr(invite, "email", "") or "").strip().lower()
    member_id = payload.get("member_id") or getattr(invite, "member_id", None)

    if not email or not member_id:
        raise ValueError("Invite payload invalid")

    user = User.objects.get(email=email)
    member = BusinessMember.objects.select_for_update().get(id=member_id, user=user)

    validate_password(password, user=user)

    user.first_name = first_name or ""
    user.last_name = last_name or ""
    user.set_password(password)
    user.role = "EMPLOYEE"

    user_update_fields = ["first_name", "last_name", "password", "role"]
    if not getattr(user, "username", ""):
        user.username = email
        user_update_fields.append("username")

    user.save(update_fields=user_update_fields)

    member.is_active = True
    if hasattr(member, "terminated_at"):
        member.terminated_at = None
        member.save(update_fields=["is_active", "terminated_at"])
    else:
        member.save(update_fields=["is_active"])

    if hasattr(invite, "used_at"):
        invite.used_at = timezone.now()
    if hasattr(invite, "used_by"):
        invite.used_by = user

    invite_update_fields = []
    if hasattr(invite, "used_at"):
        invite_update_fields.append("used_at")
    if hasattr(invite, "used_by"):
        invite_update_fields.append("used_by")
    if invite_update_fields:
        invite.save(update_fields=invite_update_fields)

    token, _ = Token.objects.get_or_create(user=user)

    return {
        "token": token.key,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": getattr(user, "role", None),
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