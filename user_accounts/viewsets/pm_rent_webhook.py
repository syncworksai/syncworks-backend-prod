# backend/user_accounts/viewsets/pm_rent_webhook.py
from __future__ import annotations

from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import PMRentCharge, PMRentPayment


def _money_from_cents(cents) -> Decimal:
    try:
        if cents is None:
            return Decimal("0.00")
        return (Decimal(int(cents)) / Decimal("100")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _safe_recompute_charge(charge: PMRentCharge) -> None:
    """
    Your codebase has evolved (paid_total/balance_due/status vs paid_amount, etc).
    Be defensive and call whichever recompute method exists.
    """
    fn = getattr(charge, "recompute", None)
    if callable(fn):
        fn()
        return
    fn2 = getattr(charge, "recompute_status", None)
    if callable(fn2):
        fn2()
        return


class PMRentWebhookAPIView(APIView):
    """
    Stripe -> PM Rent Webhook
    - Verifies signature (STRIPE_WEBHOOK_SECRET)
    - Records a PMRentPayment for checkout.session.completed
    - Idempotent by stripe_event_id (or fallback to session_id if needed)
    """

    authentication_classes = []  # Stripe will not send auth headers
    permission_classes = []

    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        if not secret:
            return Response(
                {"detail": "STRIPE_WEBHOOK_SECRET not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")

        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=secret,
            )
        except ValueError:
            return Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get("type")
        event_id = (event.get("id") or "").strip()
        data_obj = (event.get("data") or {}).get("object") or {}

        # Only act on completed checkout sessions (rent payments)
        if event_type != "checkout.session.completed":
            return Response({"ok": True, "ignored": True, "type": event_type}, status=status.HTTP_200_OK)

        session_id = (data_obj.get("id") or "").strip()
        payment_intent = (data_obj.get("payment_intent") or "").strip()
        amount_total = data_obj.get("amount_total")
        metadata = data_obj.get("metadata") or {}

        # Prefer metadata charge_id if present, else fallback to stored session_id
        charge_id = metadata.get("charge_id")

        charge = None
        if charge_id:
            charge = PMRentCharge.objects.filter(id=charge_id).first()
        if charge is None and session_id:
            charge = PMRentCharge.objects.filter(stripe_checkout_session_id=session_id).first()

        if charge is None:
            return Response({"ok": True, "ignored": True, "reason": "no_matching_charge"}, status=status.HTTP_200_OK)

        amount = _money_from_cents(amount_total)

        try:
            with transaction.atomic():
                # ---- Idempotency guards ----
                if hasattr(PMRentPayment, "stripe_event_id") and event_id:
                    if PMRentPayment.objects.filter(stripe_event_id=str(event_id)).exists():
                        return Response({"ok": True, "duplicate": True}, status=status.HTTP_200_OK)

                # Fallback idempotency if your model doesn't have stripe_event_id yet
                if not hasattr(PMRentPayment, "stripe_event_id") and session_id:
                    if PMRentPayment.objects.filter(stripe_session_id=str(session_id)).exists():
                        return Response({"ok": True, "duplicate": True}, status=status.HTTP_200_OK)

                # If Stripe amount is missing/zero, record remaining balance instead
                if amount <= Decimal("0.00"):
                    _safe_recompute_charge(charge)
                    # Some codebases store balance_due as a field, others as a property
                    bd = getattr(charge, "balance_due", None)
                    amount = bd if isinstance(bd, Decimal) else Decimal("0.00")
                    if amount <= Decimal("0.00"):
                        return Response({"ok": True, "ignored": True, "reason": "zero_amount"}, status=status.HTTP_200_OK)

                # ---- Build create kwargs safely ----
                create_kwargs = dict(
                    charge=charge,
                    amount=amount,
                    paid_at=timezone.now(),
                    method="STRIPE",
                    reference=f"Checkout Session {session_id}".strip(),
                    stripe_payment_intent_id=str(payment_intent or ""),
                )

                # business is REQUIRED in some versions of your model
                if "business" in [f.name for f in PMRentPayment._meta.fields]:
                    create_kwargs["business"] = charge.business

                # optional fields depending on your schema
                if hasattr(PMRentPayment, "stripe_event_id"):
                    create_kwargs["stripe_event_id"] = str(event_id or "")
                if hasattr(PMRentPayment, "stripe_session_id"):
                    create_kwargs["stripe_session_id"] = str(session_id or "")

                PMRentPayment.objects.create(**create_kwargs)

                # Recompute charge totals/status
                _safe_recompute_charge(charge)

                # Save only fields that actually exist on the model
                update_fields = []
                for field in ["paid_total", "paid_amount", "balance_due", "status", "updated_at"]:
                    try:
                        charge._meta.get_field(field)
                        update_fields.append(field)
                    except Exception:
                        pass

                if update_fields:
                    charge.save(update_fields=update_fields)
                else:
                    charge.save()

        except Exception as e:
            # In dev, it's helpful to see the error; in prod, you'd log and return generic 500.
            if settings.DEBUG:
                return Response(
                    {"detail": "Webhook failed", "error": str(e), "event_id": event_id, "session_id": session_id},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            return Response({"detail": "Webhook failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"ok": True, "charge_id": charge.id, "amount": str(amount)}, status=status.HTTP_200_OK)
