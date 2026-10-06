from rest_framework import serializers

from user_accounts.models.finance_payments import FinanceDebtPayment


class FinanceDebtPaymentSerializer(serializers.ModelSerializer):
    liability_name = serializers.CharField(source="liability.name", read_only=True)

    class Meta:
        model = FinanceDebtPayment
        fields = "__all__"
        read_only_fields = [
            "user",
            "source",
            "status",
            "balance_before",
            "balance_after",
            "principal_amount",
            "interest_amount",
            "fee_amount",
            "estimated_interest_saved_next_30_days",
            "provider_reference",
            "metadata",
            "created_at",
            "updated_at",
        ]
