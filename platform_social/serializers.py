from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import (
    Collection,
    CollectionPayment,
    CollectionShare,
    Connection,
    EventMemberResponse,
    GroupEventInvitation,
    GroupInviteLink,
    GroupMessage,
    GroupMembership,
    GroupPaymentSettings,
    SocialEvent,
    SocialGroup,
)

User = get_user_model()


class SocialUserSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "display_name")
        read_only_fields = fields

    def get_display_name(self, obj):
        full_name = f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}".strip()
        return full_name or getattr(obj, "email", "")


class ConnectionSerializer(serializers.ModelSerializer):
    sender_detail = SocialUserSerializer(source="sender", read_only=True)
    recipient_detail = SocialUserSerializer(source="recipient", read_only=True)

    class Meta:
        model = Connection
        fields = (
            "id", "sender", "recipient", "sender_detail", "recipient_detail", "status",
            "responded_at", "created_at", "updated_at",
        )
        read_only_fields = ("id", "sender", "status", "responded_at", "created_at", "updated_at")

    def validate_recipient(self, value):
        request = self.context.get("request")
        if request and value.pk == request.user.pk:
            raise serializers.ValidationError("You cannot connect to yourself.")
        return value


class GroupMembershipSerializer(serializers.ModelSerializer):
    user_detail = SocialUserSerializer(source="user", read_only=True)
    invited_by_detail = SocialUserSerializer(source="invited_by", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)

    class Meta:
        model = GroupMembership
        fields = (
            "id", "group", "group_name", "user", "user_detail", "role", "status",
            "invited_by", "invited_by_detail", "created_at", "updated_at",
        )
        read_only_fields = ("id", "invited_by", "invited_by_detail", "group_name", "created_at", "updated_at")


class GroupInviteLinkSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True)
    created_by_detail = SocialUserSerializer(source="created_by", read_only=True)
    usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = GroupInviteLink
        fields = (
            "id", "group", "group_name", "token", "role", "created_by", "created_by_detail",
            "is_active", "expires_at", "max_uses", "uses_count", "usable", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "token", "created_by", "created_by_detail", "uses_count", "usable", "created_at", "updated_at",
        )


class GroupPaymentSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupPaymentSettings
        fields = (
            "id", "group", "cash_app_url", "cash_app_label", "venmo_url", "venmo_label",
            "zelle_instructions", "stripe_payment_link", "platform_fee_bps", "updated_by",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "platform_fee_bps", "updated_by", "created_at", "updated_at")


class GroupMessageSerializer(serializers.ModelSerializer):
    author_detail = SocialUserSerializer(source="author", read_only=True)

    class Meta:
        model = GroupMessage
        fields = (
            "id", "group", "author", "author_detail", "body", "is_deleted",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "author", "author_detail", "is_deleted", "created_at", "updated_at",
        )

    def validate_body(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value


class SocialGroupSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(source="memberships.count", read_only=True)

    class Meta:
        model = SocialGroup
        fields = (
            "id", "name", "description", "kind", "visibility", "parent", "created_by",
            "city", "state", "logo_url", "is_active", "member_count", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "member_count", "created_at", "updated_at")


class SocialEventSerializer(serializers.ModelSerializer):
    invitation_count = serializers.IntegerField(source="group_invitations.count", read_only=True)

    class Meta:
        model = SocialEvent
        fields = (
            "id", "organizer_group", "created_by", "title", "description", "start_at", "end_at",
            "timezone", "recurrence_rule", "weather_dependent", "weather_note", "venue_name", "address_line1",
            "address_line2", "city", "state", "postal_code", "country", "entry_amount_cents", "payment_due_at",
            "prizes", "rules", "flyer_url", "status", "version", "invitation_count", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "version", "invitation_count", "created_at", "updated_at")

    def validate(self, attrs):
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(self.instance, "end_at", None))
        if start_at and end_at and end_at < start_at:
            raise serializers.ValidationError({"end_at": "End time cannot be before start time."})
        return attrs


class GroupEventInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupEventInvitation
        fields = (
            "id", "event", "target_group", "invited_by", "status", "responded_by", "responded_at",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "invited_by", "status", "responded_by", "responded_at", "created_at", "updated_at")


class EventMemberResponseSerializer(serializers.ModelSerializer):
    user_detail = SocialUserSerializer(source="user", read_only=True)

    class Meta:
        model = EventMemberResponse
        fields = ("id", "event", "group", "user", "user_detail", "response", "responded_at", "created_at", "updated_at")
        read_only_fields = ("id", "user", "responded_at", "created_at", "updated_at")

    def create(self, validated_data):
        user = validated_data["user"]
        event = validated_data["event"]
        group = validated_data["group"]
        defaults = {
            "response": validated_data.get("response", EventMemberResponse.Response.PENDING),
            "responded_at": validated_data.get("responded_at"),
        }
        instance, _ = EventMemberResponse.objects.update_or_create(
            event=event,
            group=group,
            user=user,
            defaults=defaults,
        )
        return instance


class CollectionShareSerializer(serializers.ModelSerializer):
    user_detail = SocialUserSerializer(source="user", read_only=True)

    class Meta:
        model = CollectionShare
        fields = (
            "id", "collection", "user", "user_detail", "amount_due_cents", "amount_paid_cents", "quantity",
            "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "amount_paid_cents", "status", "created_at", "updated_at")


class CollectionPaymentSerializer(serializers.ModelSerializer):
    payer_detail = SocialUserSerializer(source="payer", read_only=True)

    class Meta:
        model = CollectionPayment
        fields = (
            "id", "collection", "share", "payer", "payer_detail", "method",
            "gross_amount_cents", "platform_fee_bps", "platform_fee_cents", "fee_status",
            "external_reference", "created_by", "created_at",
        )
        read_only_fields = (
            "id", "platform_fee_bps", "platform_fee_cents", "fee_status", "created_by", "created_at",
        )


class CollectionSerializer(serializers.ModelSerializer):
    shares = CollectionShareSerializer(many=True, read_only=True)
    collected_amount_cents = serializers.SerializerMethodField()
    payment_options = serializers.SerializerMethodField()
    platform_fee_amount_cents = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = (
            "id", "group", "event", "created_by", "title", "description", "total_amount_cents", "split_method",
            "due_at", "status", "platform_fee_bps", "platform_fee_amount_cents",
            "collected_amount_cents", "payment_options", "shares", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "created_by", "platform_fee_bps", "platform_fee_amount_cents",
            "collected_amount_cents", "payment_options", "shares", "created_at", "updated_at",
        )

    def get_collected_amount_cents(self, obj):
        return sum(share.amount_paid_cents for share in obj.shares.all())

    def get_platform_fee_amount_cents(self, obj):
        return (int(obj.total_amount_cents or 0) * 100 + 5000) // 10000

    def get_payment_options(self, obj):
        try:
            settings = obj.group.payment_settings
        except GroupPaymentSettings.DoesNotExist:
            return {
                "cash_app_url": "", "cash_app_label": "", "venmo_url": "", "venmo_label": "",
                "zelle_instructions": "", "stripe_payment_link": "", "platform_fee_bps": 100,
            }
        return GroupPaymentSettingsSerializer(settings).data
