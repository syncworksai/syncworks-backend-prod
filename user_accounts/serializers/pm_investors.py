# backend/user_accounts/serializers/pm_investors.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_investor import PMInvestor


class PMInvestorSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMInvestor
        fields = [
            "id",
            "user",
            "full_name",
            "email",
            "phone",
            "status",
            "claim_code",
            "claim_code_created_at",
            "claimed_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "claim_code",
            "claim_code_created_at",
            "claimed_at",
            "created_at",
            "updated_at",
        ]


class PMInvestorClaimSerializer(serializers.Serializer):
    """
    Investor enters claim_code while logged in.
    We bind PMInvestor.user = request.user.
    """

    claim_code = serializers.CharField(max_length=64)
