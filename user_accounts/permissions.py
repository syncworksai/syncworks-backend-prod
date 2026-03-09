# backend/user_accounts/permissions.py
from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from user_accounts.models import Business, BusinessMember, Ticket
from user_accounts.services.tickets import marketplace_tickets_for_business


# ----------------------------
# Shared helpers
# ----------------------------

def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))


def _role_is(user, *roles: str) -> bool:
    r = (getattr(user, "role", "") or "").upper()
    return r in {x.upper() for x in roles}


def _get_active_business_id(request, view=None) -> int | None:
    """
    Multi-tenant "active business" detector.
    Tries (in order):
      1) X-Business-Id header
      2) ?business_id= query param
      3) view.kwargs['business_pk'/'business_id'/'pk'] (fallback)
    """
    # Header
    bid = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if bid:
        try:
            return int(bid)
        except Exception:
            return None

    # Query param
    bid = request.query_params.get("business_id") or request.query_params.get("business")
    if bid:
        try:
            return int(bid)
        except Exception:
            return None

    # View kwargs (best-effort)
    if view is not None:
        kwargs = getattr(view, "kwargs", {}) or {}
        for k in ("business_id", "business_pk", "pk"):
            if k in kwargs:
                try:
                    return int(kwargs[k])
                except Exception:
                    continue

    return None


def _get_membership(user, business_id: int) -> BusinessMember | None:
    return (
        BusinessMember.objects.filter(user_id=user.id, business_id=business_id, is_active=True)
        .select_related("business")
        .first()
    )


def _user_can_manage_team(member: BusinessMember | None, user, business: Business | None) -> bool:
    """
    Best-effort: supports multiple schemas.
    Allows:
      - Platform admin
      - Business.owner_id == user.id
      - BusinessMember.is_owner True
      - BusinessMember.can_manage_team True (if field exists)
      - BusinessMember.role in common elevated roles (if field exists)
    """
    if _is_platform_admin(user):
        return True

    if business and getattr(business, "owner_id", None) == getattr(user, "id", None):
        return True

    if not member:
        return False

    if bool(getattr(member, "is_owner", False)):
        return True

    # Common boolean flag
    if getattr(member, "can_manage_team", False):
        return True

    # Some schemas store a role for membership
    mrole = (getattr(member, "role", "") or "").upper()
    if mrole in {"OWNER", "MANAGER", "ADMIN", "DISPATCH"}:
        return True

    return False


# ----------------------------
# Marker permission: No business header required
# (Used by tenant portal / public-ish authed endpoints)
# ----------------------------

class NoBusinessHeaderRequired(BasePermission):
    """
    Marker permission used by views that should NOT require X-Business-Id.
    Keep permissive here; views should still require IsAuthenticated.
    """
    def has_permission(self, request, view) -> bool:
        return True


# ----------------------------
# Restored permissions used by team.py
# ----------------------------

class IsBusinessMember(BasePermission):
    """
    Used by team endpoints.
    Requires:
      - platform admin OR
      - SBO owner of active business OR
      - active BusinessMember in active business
    """
    message = "You are not a member of this business."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False

        if _is_platform_admin(u):
            return True

        business_id = _get_active_business_id(request, view=view)
        if not business_id:
            # If no business context, deny (prevents leakage)
            return False

        # SBO owner qualifies
        if _role_is(u, "SBO"):
            return Business.objects.filter(id=business_id, owner_id=u.id, is_active=True).exists()

        # EMPLOYEE must be a member
        return BusinessMember.objects.filter(user_id=u.id, business_id=business_id, is_active=True).exists()


class CanManageTeam(BasePermission):
    """
    Used by team endpoints.
    Requires:
      - platform admin OR
      - SBO owner of active business OR
      - BusinessMember with team management privileges (see helper)
    """
    message = "You do not have permission to manage this team."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False

        if _is_platform_admin(u):
            return True

        business_id = _get_active_business_id(request, view=view)
        if not business_id:
            return False

        business = Business.objects.filter(id=business_id, is_active=True).first()

        # SBO owner qualifies
        if business and getattr(business, "owner_id", None) == u.id:
            return True

        member = _get_membership(u, business_id)
        return _user_can_manage_team(member, u, business)


# ----------------------------
# Ticket isolation permissions (keep this!)
# ----------------------------

def _ticket_from_view(view, request) -> Ticket | None:
    tid = request.query_params.get("ticket") or request.data.get("ticket")
    if tid:
        try:
            return Ticket.objects.get(pk=int(tid))
        except Exception:
            raise NotFound("Ticket not found.")

    pk = getattr(view, "kwargs", {}).get("pk")
    if pk:
        try:
            return Ticket.objects.get(pk=int(pk))
        except Exception:
            pass

    try:
        obj = view.get_object()
    except Exception:
        return None

    if isinstance(obj, Ticket):
        return obj

    if hasattr(obj, "ticket"):
        try:
            return obj.ticket
        except Exception:
            return None

    if hasattr(obj, "ticket_id"):
        try:
            return Ticket.objects.get(pk=int(obj.ticket_id))
        except Exception:
            return None

    return None


class TicketParticipantRequired(BasePermission):
    """
    Gate access to ticket-related objects (messages/attachments/quotes/invoices).
    Allowed if:
      - platform admin / superuser
      - customer who owns the ticket
      - SBO who owns the assigned business OR can see the marketplace ticket (eligible)
      - EMPLOYEE who is member of assigned business OR can see the marketplace ticket (eligible via any business they belong to)
    """
    message = "You do not have access to this ticket."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if _is_platform_admin(user):
            return True

        ticket = _ticket_from_view(view, request)
        if ticket is None:
            # list endpoints without ?ticket= can pass; queryset filtering should still apply
            return True

        return self._user_can_access_ticket(user, ticket)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if _is_platform_admin(user):
            return True

        ticket = obj if isinstance(obj, Ticket) else getattr(obj, "ticket", None)
        if ticket is None and hasattr(obj, "ticket_id"):
            try:
                ticket = Ticket.objects.get(pk=int(obj.ticket_id))
            except Exception:
                return False

        if ticket is None:
            return False

        return self._user_can_access_ticket(user, ticket)

    @staticmethod
    def _user_can_access_ticket(user, ticket: Ticket) -> bool:
        # Customer owns it
        if _role_is(user, "CUSTOMER") and getattr(ticket, "customer_id", None) == user.id:
            return True

        biz_id = getattr(ticket, "assigned_business_id", None)
        if biz_id:
            # SBO owns assigned business
            if _role_is(user, "SBO"):
                try:
                    return ticket.assigned_business and ticket.assigned_business.owner_id == user.id
                except Exception:
                    return False

            # Employee is member of assigned business
            if _role_is(user, "EMPLOYEE"):
                return BusinessMember.objects.filter(
                    user_id=user.id,
                    business_id=biz_id,
                    is_active=True,
                ).exists()

        # Marketplace: ONLY if eligible (not global)
        if getattr(ticket, "is_marketplace", False) and _role_is(user, "SBO", "EMPLOYEE"):
            if _role_is(user, "SBO"):
                biz = Business.objects.filter(owner_id=user.id, is_active=True).first()
                if not biz:
                    return False
                eligible_ids = set(marketplace_tickets_for_business(biz).values_list("id", flat=True))
                return ticket.id in eligible_ids

            if _role_is(user, "EMPLOYEE"):
                biz_ids = list(
                    BusinessMember.objects.filter(user_id=user.id, is_active=True)
                    .values_list("business_id", flat=True)
                )
                if not biz_ids:
                    return False
                for biz in Business.objects.filter(id__in=biz_ids, is_active=True):
                    eligible_ids = set(marketplace_tickets_for_business(biz).values_list("id", flat=True))
                    if ticket.id in eligible_ids:
                        return True
                return False

        return False


# ----------------------------
# ✅ God Mode permission (needed for platform metrics + console)
# ----------------------------

class IsGodMode(BasePermission):
    """
    God Mode = email allowlist (settings.GOD_MODE_EMAIL_ALLOWLIST).
    Canonical truth lives in user_accounts.services.god_mode.is_god_mode()
    """
    message = "Not allowed."

    def has_permission(self, request, view):
        from user_accounts.services.god_mode import is_god_mode  # local import avoids circulars
        return is_god_mode(getattr(request, "user", None))