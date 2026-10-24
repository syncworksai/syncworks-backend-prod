from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import BusinessExpense, BusinessFinanceSettings, CashForecastItem, JobCostReview


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessExpense
        fields = [
            "id", "ticket", "category", "status", "description", "vendor",
            "quantity", "unit_cost", "amount", "incurred_on", "due_on", "paid_on",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "amount", "created_at", "updated_at"]

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", Decimal("1")))
        unit_cost = attrs.get("unit_cost", getattr(self.instance, "unit_cost", Decimal("0")))
        ticket = attrs.get("ticket", getattr(self.instance, "ticket", None))
        business = self.context["business"]
        if quantity <= 0:
            raise serializers.ValidationError({"quantity": "Enter a quantity greater than zero."})
        if unit_cost < 0:
            raise serializers.ValidationError({"unit_cost": "Cost cannot be negative."})
        if ticket is not None and ticket.assigned_business_id != business.id:
            raise serializers.ValidationError({"ticket": "Ticket is not in this business."})
        status = attrs.get("status", getattr(self.instance, "status", BusinessExpense.Status.INCURRED))
        paid_on = attrs.get("paid_on", getattr(self.instance, "paid_on", None))
        if status == BusinessExpense.Status.PAID and not paid_on:
            attrs["paid_on"] = timezone.localdate()
        if status != BusinessExpense.Status.PAID:
            attrs["paid_on"] = None
        return attrs


class CashForecastSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashForecastItem
        fields = ["id", "description", "direction", "status", "amount", "expected_on", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_amount(self, amount):
        if amount <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return amount


class FinanceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessFinanceSettings
        fields = ["opening_cash_balance", "opening_cash_date", "expenses_reconciled_through", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        balance = attrs.get("opening_cash_balance", getattr(self.instance, "opening_cash_balance", None))
        date = attrs.get("opening_cash_date", getattr(self.instance, "opening_cash_date", None))
        if (balance is None) != (date is None):
            raise serializers.ValidationError("Opening cash amount and snapshot date must both be provided.")
        if date and date > timezone.localdate():
            raise serializers.ValidationError({"opening_cash_date": "Snapshot date cannot be in the future."})
        reconciled = attrs.get("expenses_reconciled_through", getattr(self.instance, "expenses_reconciled_through", None))
        if reconciled and reconciled >= timezone.localdate().replace(day=1):
            raise serializers.ValidationError({"expenses_reconciled_through": "Only completed months can be reconciled."})
        return attrs


class JobCostReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobCostReview
        fields = ["ticket", "costs_complete", "reviewed_at"]
        read_only_fields = ["reviewed_at"]
