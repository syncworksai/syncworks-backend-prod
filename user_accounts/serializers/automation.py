from rest_framework import serializers

from user_accounts.models import AutomationExecution, AutomationRule


class AutomationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationRule
        fields = "__all__"
        read_only_fields = ["id", "business", "created_by", "created_at", "updated_at"]

    def validate_trigger_config(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("trigger_config must be a JSON object.")
        return value

    def validate_action_config(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("action_config must be a JSON object.")
        return value


class AutomationExecutionSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)

    class Meta:
        model = AutomationExecution
        fields = [
            "id", "rule", "rule_name", "ticket", "event", "status",
            "dedupe_key", "input_data", "output_data", "error_message",
            "executed_by", "created_at", "completed_at",
        ]
        read_only_fields = fields
