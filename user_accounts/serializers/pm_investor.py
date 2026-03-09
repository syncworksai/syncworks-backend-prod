# backend/user_accounts/serializers/pm_investor.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import (
    PMInvestor,
    PMPropertyInvestor,
    PMInboxThread,
    PMInboxMessage,
    PMNotification,
)


class PMInvestorSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMInvestor
        fields = [
            "id",
            "business_id",
            "user",
            "first_name",
            "last_name",
            "email",
            "phone",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business_id", "created_at", "updated_at"]


class PMPropertyInvestorSerializer(serializers.ModelSerializer):
    investor_id = serializers.IntegerField(source="investor.id", read_only=True)
    property_id = serializers.IntegerField(source="property.id", read_only=True)

    class Meta:
        model = PMPropertyInvestor
        fields = [
            "id",
            "business_id",
            "investor",
            "investor_id",
            "property",
            "property_id",
            "role",
            "ownership_percent",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "business_id", "investor_id", "property_id", "created_at"]


class PMInboxMessageSerializer(serializers.ModelSerializer):
    thread_id = serializers.IntegerField(source="thread.id", read_only=True)

    class Meta:
        model = PMInboxMessage
        fields = [
            "id",
            "business_id",
            "thread",
            "thread_id",
            "sender_role",
            "sender_user",
            "body",
            "created_at",
        ]
        read_only_fields = ["id", "business_id", "thread_id", "created_at"]


class PMInboxThreadSerializer(serializers.ModelSerializer):
    investor_id = serializers.IntegerField(source="investor.id", read_only=True)
    property_id = serializers.IntegerField(source="property.id", read_only=True)
    last_message_preview = serializers.SerializerMethodField()
    unread_for_pm = serializers.SerializerMethodField()
    unread_for_investor = serializers.SerializerMethodField()

    class Meta:
        model = PMInboxThread
        fields = [
            "id",
            "business_id",
            "investor",
            "investor_id",
            "property",
            "property_id",
            "subject",
            "status",
            "created_by",
            "last_message_at",
            "last_viewed_by_pm_at",
            "last_viewed_by_investor_at",
            "created_at",
            "last_message_preview",
            "unread_for_pm",
            "unread_for_investor",
        ]
        read_only_fields = ["id", "business_id", "created_at", "investor_id", "property_id", "last_message_preview", "unread_for_pm", "unread_for_investor"]

    def get_last_message_preview(self, obj: PMInboxThread) -> str:
        m = obj.messages.order_by("-created_at", "-id").first()
        if not m or not m.body:
            return ""
        s = m.body.strip()
        return s[:90] + ("…" if len(s) > 90 else "")

    def get_unread_for_pm(self, obj: PMInboxThread) -> int:
        last_seen = obj.last_viewed_by_pm_at
        qs = obj.messages.filter(sender_role=PMInboxMessage.SENDER_INVESTOR)
        if last_seen:
            qs = qs.filter(created_at__gt=last_seen)
        return qs.count()

    def get_unread_for_investor(self, obj: PMInboxThread) -> int:
        last_seen = obj.last_viewed_by_investor_at
        qs = obj.messages.filter(sender_role=PMInboxMessage.SENDER_PM)
        if last_seen:
            qs = qs.filter(created_at__gt=last_seen)
        return qs.count()


class PMNotificationSerializer(serializers.ModelSerializer):
    investor_id = serializers.IntegerField(source="investor.id", read_only=True)
    thread_id = serializers.IntegerField(source="thread.id", read_only=True)
    message_id = serializers.IntegerField(source="message.id", read_only=True)

    class Meta:
        model = PMNotification
        fields = [
            "id",
            "business_id",
            "investor",
            "investor_id",
            "notif_type",
            "title",
            "body",
            "thread",
            "thread_id",
            "message",
            "message_id",
            "read_at",
            "created_at",
        ]
        read_only_fields = ["id", "business_id", "investor_id", "thread_id", "message_id", "created_at"]
