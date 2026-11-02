"""Read-only Stripe recurring price checks. Never creates prices or subscriptions."""
import os
import stripe

# Expected monthly USD prices in cents, approved for the pricing preview.
MONTHLY_FEATURE_PRICES = {
    "automated_email": 99,
    "technician_tracking": 999,
    "ai_assistant": 1999,
    "ai_weather": 99,
    "ai_traffic": 99,
    "smart_routes": 999,
    "ai_phone": 1999,
    "business_jarvis": 3999,
}

PRICE_ENV = {key: "STRIPE_PRICE_FEATURE_" + key.upper() for key in MONTHLY_FEATURE_PRICES}

def inspect_stripe_prices():
    """Validate configured prices using current environment credentials. Fail closed."""
    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        return {feature: {"valid": False, "reason": "Stripe API key not configured"} for feature in MONTHLY_FEATURE_PRICES}
    stripe.api_key = secret
    result = {}
    for feature, expected in MONTHLY_FEATURE_PRICES.items():
        price_id = (os.getenv(PRICE_ENV[feature]) or "").strip()
        if not price_id:
            result[feature] = {"valid": False, "reason": "Price not configured"}
            continue
        try:
            price = stripe.Price.retrieve(price_id)
            recurring = price.get("recurring") or {}
            valid = bool(price.get("active") and price.get("currency") == "usd"
                         and recurring.get("interval") == "month"
                         and int(recurring.get("interval_count") or 1) == 1
                         and price.get("billing_scheme") == "per_unit"
                         and int(price.get("unit_amount") or -1) == expected)
            result[feature] = {"valid": valid, "reason": "verified" if valid else "Wrong amount, currency, interval or disabled price"}
        except Exception:
            result[feature] = {"valid": False, "reason": "Stripe price could not be verified"}
    return result
