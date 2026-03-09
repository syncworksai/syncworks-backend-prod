from rest_framework import serializers

from user_accounts.models import BusinessMember, BusinessMemberRole, InviteCode


class BusinessMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = BusinessMember
        fields = [
            "id",
            "business",
            "user",
            "user_email",
            "role",
            "is_active",
            "terminated_at",
            # permission booleans
            "can_view_invoices",
            "can_send_quotes",
            "can_assign_tickets",
            "can_manage_team",
            "can_post_internal_messages",
        ]
        read_only_fields = ["id", "business", "user", "user_email", "terminated_at"]


class EmployeeInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=BusinessMemberRole.choices)
    permissions = serializers.DictField(
        child=serializers.BooleanField(),
        required=False,
        help_text="Optional permission map, e.g. {can_assign_tickets:true}",
    )


class EmployeeInviteResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = InviteCode
        fields = ["code", "kind", "expires_at", "used_at", "payload"]


class EmployeeInviteAcceptSerializer(serializers.Serializer):
    code = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)
