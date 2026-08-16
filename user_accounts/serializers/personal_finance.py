from rest_framework import serializers

from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceBudget,
    FinanceConnection,
    FinanceGoal,
    FinanceLiability,
    FinanceObligation,
    FinanceTransaction,
)


class FinanceConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceConnection
        exclude = ["encrypted_access_token"]
        read_only_fields = ["user", "provider_item_id", "cursor", "last_synced_at", "last_error", "created_at", "updated_at"]


class FinanceAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceAccount
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class FinanceLiabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceLiability
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class FinanceObligationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceObligation
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class FinanceTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceTransaction
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class FinanceGoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceGoal
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]


class FinanceBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceBudget
        fields = "__all__"
        read_only_fields = ["user", "created_at", "updated_at"]
