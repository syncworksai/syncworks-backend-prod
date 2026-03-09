# backend/user_accounts/api/pm_rent_b2_router.py
from user_accounts.api.pm_rent_b2 import PMRentPaymentB2ViewSet, PMRentChargeB2ActionsViewSet


def register_pm_rent_b2_routes(router):
    """
    Call this once in the same place you already do router.register(...)
    so we DO NOT touch your existing rent charge endpoints.

    Adds:
      /api/v1/pm/rent/payments/record/
      /api/v1/pm/rent/charges/adjust/
    """
    router.register(r"pm/rent/payments", PMRentPaymentB2ViewSet, basename="pm-rent-payments-b2")
    # Note: we register a separate viewset so your existing ChargesViewSet stays untouched.
    router.register(r"pm/rent/charges", PMRentChargeB2ActionsViewSet, basename="pm-rent-charges-b2-actions")
