# user_accounts/serializers/team.py
from rest_framework import serializers
from django.utils import timezone

from user_accounts.models import BusinessMember, InviteCode, Business


class BusinessMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMember
        fields = [
            "id",
            "business",
            "user",
            "user_email",
            "user_name",
            "role",
            "is_active",
            # permissions
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
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "business", "user"]

    def get_user_email(self, obj):
        try:
            return obj.user.email
        except Exception:
            return None

    def get_user_name(self, obj):
        try:
            fn = obj.user.first_name or ""
            ln = obj.user.last_name or ""
            name = (fn + " " + ln).strip()
            return name or obj.user.username
        except Exception:
            return None


class InviteCodeSerializer(serializers.ModelSerializer):
    """
    Serializer for InviteCode model used by:
      - GET /team/invites/
      - POST /team/invites/ (create)
    """

    class Meta:
        model = InviteCode
        fields = [
            "id",
            "business",
            "created_by",
            "email",
            "code",
            "role",
            # permissions snapshot
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
            "created_at",
            "expires_at",
            "used_at",
            "accepted_by",
        ]
        read_only_fields = [
            "id",
            "business",
            "created_by",
            "code",
            "created_at",
            "used_at",
            "accepted_by",
        ]

    def validate(self, attrs):
        # If email is present, normalize
        email = attrs.get("email")
        if email:
            attrs["email"] = email.strip().lower()
        return attrs


class InviteAcceptSerializer(serializers.Serializer):
    """
    Used by POST /team/invites/accept/ (or whatever endpoint your viewset exposes)
    """
    code = serializers.CharField()

    def validate_code(self, value):
        code = (value or "").strip()
        if not code:
            raise serializers.ValidationError("Invite code is required.")
        return code

    def validate(self, attrs):
        code = attrs["code"]

        invite = InviteCode.objects.filter(code=code).first()
        if not invite:
            raise serializers.ValidationError({"code": "Invalid invite code."})

        if invite.used_at is not None:
            raise serializers.ValidationError({"code": "This invite has already been used."})

        if invite.expires_at and timezone.now() > invite.expires_at:
            raise serializers.ValidationError({"code": "This invite is expired."})

        attrs["invite"] = invite
        return attrs
