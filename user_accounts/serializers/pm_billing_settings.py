from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_billing_settings import PMBillingSettings


class PMBillingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMBillingSettings
        fields = [
            "id",
            "business_id",
            "rent_due_day",
            "grace_days",
            "late_fee_enabled",
            "late_fee_type",
            "late_fee_flat_amount",
            "late_fee_percent",
            "auto_email_enabled",
            "email_send_on_due",
            "email_send_on_past_due",
            "email_send_on_late_fee",
            "remind_days_before_due",
            "remind_days_after_due",
            "from_name",
            "from_email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business_id", "created_at", "updated_at"]

    def validate_rent_due_day(self, v: int) -> int:
        # keep it safe for month lengths; your comment says 1..28 recommended
        if v < 1 or v > 28:
            raise serializers.ValidationError("rent_due_day must be between 1 and 28.")
        return v

    def validate_grace_days(self, v: int) -> int:
        if v < 0 or v > 31:
            raise serializers.ValidationError("grace_days must be between 0 and 31.")
        return v

    def validate_remind_days_before_due(self, v: int) -> int:
        if v < 0 or v > 31:
            raise serializers.ValidationError("remind_days_before_due must be between 0 and 31.")
        return v

    def validate_remind_days_after_due(self, v: int) -> int:
        if v < 0 or v > 31:
            raise serializers.ValidationError("remind_days_after_due must be between 0 and 31.")
        return v

    def validate(self, attrs):
        # If late fees enabled, validate type-specific fields a bit
        late_fee_enabled = attrs.get("late_fee_enabled", None)
        late_fee_type = attrs.get("late_fee_type", None)

        # For PATCH, values may be absent; rely on instance values
        if self.instance:
            if late_fee_enabled is None:
                late_fee_enabled = self.instance.late_fee_enabled
            if late_fee_type is None:
                late_fee_type = self.instance.late_fee_type

        if late_fee_enabled:
            if late_fee_type == "PCT":
                pct = attrs.get("late_fee_percent", None)
                if pct is None and self.instance:
                    pct = self.instance.late_fee_percent
                if pct is not None and pct < 0:
                    raise serializers.ValidationError({"late_fee_percent": "Must be >= 0."})
            else:
                flat = attrs.get("late_fee_flat_amount", None)
                if flat is None and self.instance:
                    flat = self.instance.late_fee_flat_amount
                if flat is not None and flat < 0:
                    raise serializers.ValidationError({"late_fee_flat_amount": "Must be >= 0."})

        return attrs
