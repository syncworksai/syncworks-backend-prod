from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class PMEmployeeRole(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    MANAGER = "MANAGER", "Manager"
    ACCOUNTING = "ACCOUNTING", "Accounting"
    LEASING = "LEASING", "Leasing"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    TECHNICIAN = "TECHNICIAN", "Technician"
    VIEW_ONLY = "VIEW_ONLY", "View Only"


def _default_invite_code() -> str:
    # short, URL-safe code
    return secrets.token_urlsafe(16)


def _default_invite_expires_at():
    # Django migrations MUST be able to serialize this callable (no lambdas)
    return timezone.now() + timedelta(days=14)


class PMEmployee(models.Model):
    """
    PM Employees live under a Business (same multi-tenant scoping as PMProperty/PMUnit).
    They can be linked to an existing User (single sign-on) OR remain "unlinked" until invited.
    """

    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="pm_employees",
    )

    # Optional single-sign-on link to an existing account user
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pm_employee_profiles",
    )

    email = models.EmailField()
    full_name = models.CharField(max_length=200, blank=True, default="")
    job_title = models.CharField(max_length=120, blank=True, default="")
    role = models.CharField(max_length=30, choices=PMEmployeeRole.choices, default=PMEmployeeRole.VIEW_ONLY)

    # Permissions (fine-grained; UI will hide tabs/sections based on these)
    can_view_financials = models.BooleanField(default=False)     # rent roll, ledger, payouts, owner statements
    can_manage_financials = models.BooleanField(default=False)   # record payments, create charges, refunds
    can_manage_properties = models.BooleanField(default=False)   # create/edit properties/units
    can_manage_tenants = models.BooleanField(default=False)      # add/edit tenants, invites, move-ins/outs
    can_manage_documents = models.BooleanField(default=False)    # upload/manage docs, request signatures
    can_manage_work_orders = models.BooleanField(default=False)  # create/assign/close work orders
    can_manage_employees = models.BooleanField(default=False)    # add/remove employees, roles

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "email"]),
            models.Index(fields=["business", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["business", "email"], name="uniq_pm_employee_business_email"),
        ]

    def __str__(self) -> str:
        return f"PMEmployee({self.email}) b={self.business_id}"

    def apply_role_defaults(self) -> None:
        """
        Optional helper: call this when setting role to auto-fill typical permissions.
        We keep it conservative: admin/manager get more, tech/maintenance get less.
        """
        r = (self.role or "").upper()

        # reset
        self.can_view_financials = False
        self.can_manage_financials = False
        self.can_manage_properties = False
        self.can_manage_tenants = False
        self.can_manage_documents = False
        self.can_manage_work_orders = False
        self.can_manage_employees = False

        if r == PMEmployeeRole.ADMIN:
            self.can_view_financials = True
            self.can_manage_financials = True
            self.can_manage_properties = True
            self.can_manage_tenants = True
            self.can_manage_documents = True
            self.can_manage_work_orders = True
            self.can_manage_employees = True

        elif r == PMEmployeeRole.MANAGER:
            self.can_view_financials = True
            self.can_manage_properties = True
            self.can_manage_tenants = True
            self.can_manage_documents = True
            self.can_manage_work_orders = True

        elif r == PMEmployeeRole.ACCOUNTING:
            self.can_view_financials = True
            self.can_manage_financials = True

        elif r == PMEmployeeRole.LEASING:
            self.can_manage_tenants = True
            self.can_manage_documents = True

        elif r in (PMEmployeeRole.MAINTENANCE, PMEmployeeRole.TECHNICIAN):
            self.can_manage_work_orders = True

        elif r == PMEmployeeRole.VIEW_ONLY:
            pass


class PMEmployeeInvite(models.Model):
    """
    Invite an employee by email to join a Business as PMEmployee.
    This supports:
    - SSO: invite email matches existing user email -> link
    - Separate login: invited user can register and accept
    """

    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="pm_employee_invites",
    )

    employee = models.ForeignKey(
        "user_accounts.PMEmployee",
        on_delete=models.CASCADE,
        related_name="invites",
        null=True,
        blank=True,
        help_text="Optional: invite tied to a pre-created PMEmployee record.",
    )

    email = models.EmailField()
    code = models.CharField(max_length=64, unique=True, default=_default_invite_code)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pm_employee_invites_created",
    )

    expires_at = models.DateTimeField(default=_default_invite_expires_at)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "email"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self) -> str:
        return f"PMEmployeeInvite({self.email}) b={self.business_id}"

    @property
    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        if self.accepted_at:
            return False
        return timezone.now() <= self.expires_at
