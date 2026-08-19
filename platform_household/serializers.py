from rest_framework import serializers

from platform_social.models import SocialGroup
from platform_social.serializers import SocialUserSerializer

from .models import HouseholdGoal, HouseholdMemberSettings, HouseholdProfile, MealPlanEntry, SharedTask, ShoppingItem


class HouseholdMemberSettingsSerializer(serializers.ModelSerializer):
    user_detail = SocialUserSerializer(source="user", read_only=True)

    class Meta:
        model = HouseholdMemberSettings
        fields = (
            "id", "household", "user", "user_detail", "share_calendar", "share_tasks", "share_shopping",
            "share_meals", "share_goals", "share_finance_summary", "share_finance_accounts", "share_finance_bills",
            "share_finance_income", "share_finance_transactions", "share_finance_budgets", "availability_status",
            "phone_available", "computer_available", "updated_at",
        )
        read_only_fields = ("id", "user", "user_detail", "updated_at")


class HouseholdProfileSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True)
    member_settings = HouseholdMemberSettingsSerializer(many=True, read_only=True)

    class Meta:
        model = HouseholdProfile
        fields = (
            "id", "group", "group_name", "address_line1", "address_line2", "city", "state", "postal_code", "country",
            "timezone", "created_by", "member_settings", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "member_settings", "created_at", "updated_at")

    def validate_group(self, value):
        if value.kind != SocialGroup.Kind.HOUSEHOLD:
            raise serializers.ValidationError("Only an explicit HOUSEHOLD group can become a Household workspace.")
        return value


class SharedTaskSerializer(serializers.ModelSerializer):
    created_by_detail = SocialUserSerializer(source="created_by", read_only=True)
    assigned_to_detail = SocialUserSerializer(source="assigned_to", read_only=True)

    class Meta:
        model = SharedTask
        fields = "__all__"
        read_only_fields = ("created_by", "completed_at", "created_at", "updated_at")


class ShoppingItemSerializer(serializers.ModelSerializer):
    added_by_detail = SocialUserSerializer(source="added_by", read_only=True)
    checked_by_detail = SocialUserSerializer(source="checked_by", read_only=True)

    class Meta:
        model = ShoppingItem
        fields = "__all__"
        read_only_fields = ("added_by", "checked_by", "checked_at", "created_at", "updated_at")


class HouseholdGoalSerializer(serializers.ModelSerializer):
    assigned_to_detail = SocialUserSerializer(source="assigned_to", read_only=True)

    class Meta:
        model = HouseholdGoal
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "updated_at")


class MealPlanEntrySerializer(serializers.ModelSerializer):
    assigned_to_detail = SocialUserSerializer(source="assigned_to", many=True, read_only=True)

    class Meta:
        model = MealPlanEntry
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "updated_at")
