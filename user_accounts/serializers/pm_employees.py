# backend/user_accounts/serializers/pm_employees.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_employees import PMEmployee, PMEmployeeInvite


class PMEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMEmployee
        fields = [
            "id",
            "business_id",
            "user_id",
            "email",
            "full_name",
            "job_title",
            "role",
            "can_view_financials",
            "can_manage_financials",
            "can_manage_properties",
            "can_manage_tenants",
            "can_manage_documents",
            "can_manage_work_orders",
            "can_manage_employees",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business_id", "user_id", "created_at", "updated_at"]


class PMEmployeeInviteSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = PMEmployeeInvite
        fields = [
            "id",
            "business_id",
            "employee_id",
            "email",
            "code",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "is_active",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "business_id",
            "employee_id",
            "code",
            "accepted_at",
            "revoked_at",
            "is_active",
            "created_at",
        ]


class PMEmployeeInviteCreateSerializer(serializers.Serializer):
    """
    Create an invite (optionally also create/update a placeholder PMEmployee with role/permissions).
    """
    email = serializers.EmailField()

    # Optional: attach to an existing employee record
    employee_id = serializers.IntegerField(required=False, allow_null=True)

    # Optional: create employee record if not provided
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    job_title = serializers.CharField(required=False, allow_blank=True, max_length=120)

    # Must match model choices: ADMIN, MANAGER, ACCOUNTING, LEASING, MAINTENANCE, TECHNICIAN, VIEW_ONLY
    role = serializers.ChoiceField(
        required=False,
        choices=[
            "ADMIN",
            "MANAGER",
            "ACCOUNTING",
            "LEASING",
            "MAINTENANCE",
            "TECHNICIAN",
            "VIEW_ONLY",
        ],
    )

    # Optional permission flags (defaults will come from model defaults)
    can_view_financials = serializers.BooleanField(required=False)
    can_manage_financials = serializers.BooleanField(required=False)
    can_manage_properties = serializers.BooleanField(required=False)
    can_manage_tenants = serializers.BooleanField(required=False)
    can_manage_documents = serializers.BooleanField(required=False)
    can_manage_work_orders = serializers.BooleanField(required=False)
    can_manage_employees = serializers.BooleanField(required=False)


class PMEmployeeInviteAcceptSerializer(serializers.Serializer):
    code = serializers.CharField()
