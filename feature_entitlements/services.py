import os
from decimal import Decimal, ROUND_CEILING
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import BusinessFeatureEntitlement, BusinessAIBudget, FEATURES

DEFAULT_BUDGET_CENTS = 200  # $2 internal provider-cost ceiling per business/month; not a customer charge

def has_feature(business, feature):
    if feature not in FEATURES: return False
    entitlement = BusinessFeatureEntitlement.objects.filter(business=business, feature=feature).first()
    return bool(entitlement and entitlement.active())

def require_feature(business, feature):
    if not has_feature(business, feature): raise PermissionDenied("This feature is not active. Review your trial or subscription.")

def provider_budget_cents():
    try: return min(max(int(os.environ.get("SYNC_AI_PROVIDER_BUDGET_CENTS", DEFAULT_BUDGET_CENTS)), 0), 10000)
    except (TypeError, ValueError): return 0

def estimate_cost_cents(input_tokens, output_tokens):
    # Costs must be explicitly configured based on the *actual* provider/model and include margin.
    try:
        input_rate = Decimal(os.environ["SYNC_AI_INPUT_USD_PER_MILLION"])
        output_rate = Decimal(os.environ["SYNC_AI_OUTPUT_USD_PER_MILLION"])
    except (KeyError, ValueError, ArithmeticError):
        raise PermissionDenied("AI metering is not configured; request blocked to prevent unbounded costs.")
    if min(input_rate, output_rate) < 0: raise PermissionDenied("Invalid AI pricing configuration.")
    if not all(isinstance(v, int) and 0 <= v <= 100000 for v in (input_tokens, output_tokens)):
        raise ValidationError("Invalid token budget.")
    dollars = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1000000)
    return int((dollars * 100).to_integral_value(rounding=ROUND_CEILING))

@transaction.atomic
def reserve_ai_cost(business, feature, input_tokens, output_tokens):
    require_feature(business, feature)
    amount = estimate_cost_cents(input_tokens, output_tokens)
    period = timezone.now().strftime("%Y-%m")
    budget, _ = BusinessAIBudget.objects.get_or_create(business=business, period=period)
    budget = BusinessAIBudget.objects.select_for_update().get(pk=budget.pk)
    ceiling = provider_budget_cents()
    if not ceiling or budget.spent_cents + budget.reserved_cents + amount > ceiling:
        raise PermissionDenied("Monthly AI allowance exhausted. No additional provider request will be made.")
    budget.reserved_cents += amount
    budget.save(update_fields=["reserved_cents"])
    return amount

@transaction.atomic
def settle_ai_cost(business, reserved_cents, actual_cents):
    if actual_cents < 0 or actual_cents > reserved_cents: raise ValidationError("Actual cost exceeds reservation.")
    period = timezone.now().strftime("%Y-%m")
    budget = BusinessAIBudget.objects.select_for_update().get(business=business, period=period)
    budget.reserved_cents -= reserved_cents
    budget.spent_cents += actual_cents
    budget.save(update_fields=["reserved_cents", "spent_cents"])

@transaction.atomic
def release_ai_reservation(business, reserved_cents):
    period = timezone.now().strftime("%Y-%m")
    budget = BusinessAIBudget.objects.select_for_update().get(business=business, period=period)
    if reserved_cents < 0 or reserved_cents > budget.reserved_cents:
        raise ValidationError("Invalid reservation release.")
    budget.reserved_cents -= reserved_cents
    budget.save(update_fields=["reserved_cents"])
