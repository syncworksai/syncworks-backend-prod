# backend/user_accounts/serializers/pm_inbox.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import PMInboxThread, PMInboxMessage


class PMInboxThreadSerializer(serializers.ModelSerializer):
    """
    Keep this robust across model tweaks:
    - We expose all fields (ModelSerializer + '__all__')
    - Frontend can pick what it needs (id, business_id, investor, property, status, created_at, etc.)
    """

    class Meta:
        model = PMInboxThread
        fields = "__all__"
        read_only_fields = ("id",)


class PMInboxMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMInboxMessage
        fields = "__all__"
        read_only_fields = ("id",)
