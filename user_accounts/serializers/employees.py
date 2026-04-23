from rest_framework import serializers

from user_accounts.models import BusinessMember, BusinessMemberRole, InviteCode


class BusinessMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = BusinessMember
        fields = [
            "id",
            "business",
            "user",
            "user_email",
            "user_first_name",
            "user_last_name",
            "role",
            "is_active",
            "terminated_at",
            "can_view_invoices",
            "can_send_quotes",
            "can_assign_tickets",
            "can_manage_team",
            "can_post_internal_messages",
            "can_manage_schedule",
            "can_close_tickets",
            "can_manage_invoices",
            "can_manage_settings",
            "can_view_financials",
            "can_create_tickets",
            "can_manage_categories",
            "can_manage_properties",
            "can_manage_connections",
        ]
        read_only_fields = [
            "id",
            "business",
            "user",
            "user_email",
            "user_first_name",
            "user_last_name",
            "terminated_at",
        ]


class EmployeeInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=BusinessMemberRole.choices)

    # HR-style onboarding fields
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)

    permissions = serializers.DictField(
        child=serializers.BooleanField(),
        required=False,
        help_text="Optional permission map, e.g. {can_assign_tickets:true}",
    )


class EmployeeInviteResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = InviteCode
        fields = [
            "id",
            "business",
            "created_by",
            "email",
            "code",
            "role",
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
            "expires_at",
            "used_at",
            "created_at",
        ]


class EmployeeInviteAcceptSerializer(serializers.Serializer):
    code = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)