from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import stripe

from django.conf import settings
from django.core.exceptions import FieldError
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.platform_billing import (
    MonthlyPlatformBill,
    PlatformBillingProfile,
    PlatformPricing,
    month_start,
    next_month_start,
)
from user_accounts.models.business import Business, BusinessMember
from user_accounts.models.billing import Invoice
from user_accounts.models.notifications import Notification
from user_accounts.models.support_requests import SupportRequest
from user_accounts.models.user_billing import UserBillingProfile
from user_accounts.models.stripe_connect import StripeConnectProfile


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


def _money_to_cents(amount) -> int:
    if amount is None:
        return 0
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _calc_paid_invoice_gross_cents(business_id: int, period_start, period_end) -> int:
    start_dt = timezone.make_aware(timezone.datetime.combine(period_start, timezone.datetime.min.time()))
    end_dt = timezone.make_aware(timezone.datetime.combine(period_end, timezone.datetime.max.time()))

    base_filters = dict(
        status__iexact="PAID",
        updated_at__gte=start_dt,
        updated_at__lte=end_dt,
    )

    def _aggregate(qs):
        agg = qs.aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))
        return _money_to_cents(agg["total"])

    try:
        invoice_model = Invoice
        business_fk_fields = [
            f.name
            for f in invoice_model._meta.fields
            if getattr(f, "remote_field", None)
            and f.remote_field
            and f.remote_field.model == Business
        ]
        for fk in business_fk_fields:
            try:
                qs = Invoice.objects.filter(**{**base_filters, f"{fk}_id": business_id})
                return _aggregate(qs)
            except FieldError:
                continue
    except Exception:
        pass

    try:
        ticket_field = Invoice._meta.get_field("ticket")
        ticket_model = ticket_field.remote_field.model

        ticket_business_fk_fields = [
            f.name
            for f in ticket_model._meta.fields
            if getattr(f, "remote_field", None)
            and f.remote_field
            and f.remote_field.model == Business
        ]

        for fk in ticket_business_fk_fields:
            try:
                qs = Invoice.objects.filter(**{**base_filters, f"ticket__{fk}_id": business_id})
                return _aggregate(qs)
            except FieldError:
                continue

        fallback_paths = [
            "ticket__business_id",
            "ticket__business__id",
            "ticket__provider_business_id",
            "ticket__provider_business__id",
            "ticket__assigned_business_id",
            "ticket__assigned_business__id",
        ]
        for path in fallback_paths:
            try:
                qs = Invoice.objects.filter(**{**base_filters, path: business_id})
                return _aggregate(qs)
            except FieldError:
                continue

    except Exception:
        pass

    return 0


def _get_business_id_from_request(request) -> int | None:
    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("X-Business-ID")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or (request.data.get("business_id") if isinstance(request.data, dict) else None)
    )
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def _get_membership(user, business_id: int) -> BusinessMember | None:
    return BusinessMember.objects.filter(business_id=business_id, user=user, is_active=True).first()


def _require_business_and_access(request):
    business_id = _get_business_id_from_request(request)
    if not business_id:
        return None, None, Response(
            {"detail": "Business context missing. Provide X-Business-Id header or ?business_id=."},
            status=400,
        )

    business = Business.objects.filter(id=business_id).first()
    if not business:
        return None, None, Response({"detail": "Business not found."}, status=404)

    if _is_platform_admin(request.user):
        return business, None, None

    if business.owner_id == request.user.id:
        membership = _get_membership(request.user, business_id)
        return business, membership, None

    membership = _get_membership(request.user, business_id)
    if not membership:
        return None, None, Response({"detail": "You are not a member of this business."}, status=403)

    return business, membership, None


def _is_billing_exempt_now(business: Business) -> bool:
    if not getattr(business, "billing_exempt", False):
        return False
    until = getattr(business, "billing_exempt_until", None)
    if not until:
        return True
    return until >= timezone.localdate()


def _is_subscriptions_exempt_now(business: Business) -> bool:
    if not getattr(business, "subscriptions_exempt", False):
        return False
    until = getattr(business, "subscriptions_exempt_until", None)
    if not until:
        return True
    return until >= timezone.localdate()


def _notify_user_ids(*, user_ids: list[int], actor, title: str, body: str, data: dict):
    if not user_ids:
        return
    Notification.objects.bulk_create(
        [
            Notification(
                recipient_id=uid,
                actor=actor,
                type=Notification.TYPE_SYSTEM,
                title=title,
                body=body,
                data=data or {},
            )
            for uid in user_ids
        ],
        batch_size=500,
    )


def _billing_recipient_user_ids(*, business: Business) -> list[int]:
    ids: set[int] = set()
    try:
        if getattr(business, "owner_id", None):
            ids.add(int(business.owner_id))
    except Exception:
        pass

    try:
        qs = BusinessMember.objects.filter(business_id=business.id, is_active=True)
        qs_role = qs
        try:
            qs_role = qs.filter(role__in=["OWNER", "MANAGER"])
        except Exception:
            qs_role = qs
        for uid in qs_role.values_list("user_id", flat=True):
            try:
                ids.add(int(uid))
            except Exception:
                pass

        try:
            for uid in qs.filter(can_manage_billing=True).values_list("user_id", flat=True):
                try:
                    ids.add(int(uid))
                except Exception:
                    pass
        except Exception:
            pass

    except Exception:
        pass

    return list(ids)


def _create_platform_inbox_item(*, requester, business_id: int, kind: str, title: str, body: str):
    try:
        since = timezone.now() - timedelta(hours=24)
        exists = SupportRequest.objects.filter(
            business_id=business_id,
            kind=kind,
            title=title[:140],
            created_at__gte=since,
        ).exists()
        if exists:
            return
    except Exception:
        pass

    try:
        SupportRequest.objects.create(
            requester=requester,
            role=getattr(requester, "role", "") or "",
            business_id=business_id,
            kind=kind,
            title=(title or "")[:140],
            body=(body or ""),
            status=SupportRequest.Status.OPEN,
        )
    except Exception:
        pass


def _maybe_send_card_expiry_alerts(*, business: Business, profile: PlatformBillingProfile, actor_user):
    days = profile.days_to_card_expiry()
    if days is None:
        return

    recipients = _billing_recipient_user_ids(business=business)

    def send(title: str, body: str, *, tag: str, days_value: int | None = None):
        data = {"business_id": business.id, "type": tag}
        if days_value is not None:
            data["days"] = int(days_value)

        _notify_user_ids(
            user_ids=recipients,
            actor=actor_user,
            title=title,
            body=body,
            data=data or {},
        )

        _create_platform_inbox_item(
            requester=actor_user,
            business_id=business.id,
            kind=SupportRequest.Kind.BILLING,
            title=f"[Billing] {title}",
            body=f"Business #{business.id} ({getattr(business, 'name', '')})\n\n{body}",
        )

    if days < 0:
        if not profile.warned_expired:
            send(
                "Payment method expired",
                "Your card on file is expired. Update billing to restore access.",
                tag="CARD_EXPIRED",
            )
            profile.warned_expired = True

        if not profile.is_locked:
            profile.lock("Card expired. Update billing method to regain access.")

        profile.save(update_fields=["warned_expired", "is_locked", "locked_at", "lock_reason"])
        return

    if days <= 1 and not profile.warned_1:
        send(
            "Card expires in 1 day",
            "Your card on file expires tomorrow. Update billing to avoid interruption.",
            tag="CARD_EXPIRING",
            days_value=1,
        )
        profile.warned_1 = True
        profile.save(update_fields=["warned_1"])
        return

    if days <= 7 and not profile.warned_7:
        send(
            "Card expires in 7 days",
            "Your card on file expires within 7 days. Update billing to avoid interruption.",
            tag="CARD_EXPIRING",
            days_value=7,
        )
        profile.warned_7 = True
        profile.save(update_fields=["warned_7"])
        return

    if days <= 15 and not profile.warned_15:
        send(
            "Card expires in 15 days",
            "Your card on file expires within 15 days. Update billing to avoid interruption.",
            tag="CARD_EXPIRING",
            days_value=15,
        )
        profile.warned_15 = True
        profile.save(update_fields=["warned_15"])
        return

    if days <= 30 and not profile.warned_30:
        send(
            "Card expires in 30 days",
            "Your card on file expires within 30 days. Update billing to avoid interruption.",
            tag="CARD_EXPIRING",
            days_value=30,
        )
        profile.warned_30 = True
        profile.save(update_fields=["warned_30"])
        return


def _dt_from_unix(ts):
    if not ts:
        return None
    try:
        return timezone.datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None


def _sync_subscription_snapshot(profile: PlatformBillingProfile, sub_obj: dict):
    if not profile or not sub_obj:
        return

    profile.stripe_subscription_id = str(sub_obj.get("id") or profile.stripe_subscription_id or "")
    profile.subscription_status = str(sub_obj.get("status") or profile.subscription_status or "")
    profile.subscription_cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end"))
    profile.subscription_current_period_end = _dt_from_unix(sub_obj.get("current_period_end"))

    profile.save(
        update_fields=[
            "stripe_subscription_id",
            "subscription_status",
            "subscription_cancel_at_period_end",
            "subscription_current_period_end",
        ]
    )


def _sync_connect_snapshot_for_business(business: Business, account_obj: dict):
    if not business or not account_obj:
        return

    account_id = str(account_obj.get("id") or "").strip()
    charges_enabled = bool(account_obj.get("charges_enabled"))
    payouts_enabled = bool(account_obj.get("payouts_enabled"))
    details_submitted = bool(account_obj.get("details_submitted"))

    requirements = account_obj.get("requirements") or {}
    currently_due = requirements.get("currently_due") or []
    past_due = requirements.get("past_due") or []
    eventually_due = requirements.get("eventually_due") or []
    disabled_reason = requirements.get("disabled_reason") or ""

    onboarding_completed = bool(
        charges_enabled
        and payouts_enabled
        and details_submitted
        and not currently_due
        and not past_due
    )

    scp, _ = StripeConnectProfile.objects.get_or_create(business=business)
    scp.charges_enabled = charges_enabled
    scp.payouts_enabled = payouts_enabled
    scp.onboarding_completed = onboarding_completed
    scp.details_submitted = details_submitted
    scp.requirements_due = {
        "currently_due": currently_due,
        "past_due": past_due,
        "eventually_due": eventually_due,
        "disabled_reason": disabled_reason,
    }
    scp.last_checked_at = timezone.now()
    scp.save()

    changed_fields: list[str] = []
    if hasattr(business, "stripe_connect_account_id") and account_id and getattr(business, "stripe_connect_account_id", "") != account_id:
        business.stripe_connect_account_id = account_id
        changed_fields.append("stripe_connect_account_id")

    if hasattr(business, "stripe_connected"):
        next_connected = bool(account_id)
        if bool(getattr(business, "stripe_connected")) != next_connected:
            business.stripe_connected = next_connected
            changed_fields.append("stripe_connected")

    if changed_fields:
        business.save(update_fields=changed_fields)


def _sync_connect_snapshot_by_account_id(account_obj: dict):
    account_id = str((account_obj or {}).get("id") or "").strip()
    if not account_id:
        return

    business = Business.objects.filter(stripe_connect_account_id=account_id).first()
    if not business:
        return

    _sync_connect_snapshot_for_business(business, account_obj)


class UserBillingStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prof, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        return Response(
            {
                "user_id": request.user.id,
                "stripe_setup_complete": bool(prof.stripe_setup_complete),
                "stripe_customer_id": prof.stripe_customer_id,
                "card_brand": prof.card_brand,
                "card_last4": prof.card_last4,
                "card_exp_month": prof.card_exp_month,
                "card_exp_year": prof.card_exp_year,
                "days_to_card_expiry": prof.days_to_card_expiry(),
            }
        )


class CreateUserSetupCheckoutSessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe authentication failed (check STRIPE_SECRET_KEY)."}, status=500)
        if not getattr(settings, "PLATFORM_BASE_URL", ""):
            return Response({"detail": "PLATFORM_BASE_URL is not configured."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        prof, _ = UserBillingProfile.objects.get_or_create(user=request.user)

        try:
            if not prof.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=getattr(request.user, "email", ""),
                    name=f"User #{request.user.id}",
                    metadata={"user_id": str(request.user.id)},
                )
                prof.stripe_customer_id = customer["id"]
                prof.save(update_fields=["stripe_customer_id"])

            success_url = f"{settings.PLATFORM_BASE_URL}/upgrade?setup=success"
            cancel_url = f"{settings.PLATFORM_BASE_URL}/upgrade?setup=cancel"

            session = stripe.checkout.Session.create(
                mode="setup",
                customer=prof.stripe_customer_id,
                payment_method_types=["card"],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"user_id": str(request.user.id)},
            )

            return Response({"url": session["url"]})

        except stripe.error.AuthenticationError as e:
            return Response(
                {"detail": "Stripe authentication failed (check STRIPE_SECRET_KEY).", "error": str(e)},
                status=500,
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error while creating setup session.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error while creating setup session.", "error": str(e)}, status=500)


class BillingStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        billing_exempt = _is_billing_exempt_now(business)
        subs_exempt = _is_subscriptions_exempt_now(business)

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)
        profile.ensure_due_dates()
        profile.save(update_fields=["next_due_date", "grace_until"])

        if not billing_exempt:
            _maybe_send_card_expiry_alerts(business=business, profile=profile, actor_user=request.user)

        today = timezone.localdate()
        days_to_due = (profile.next_due_date - today).days if profile.next_due_date else None
        days_to_lock = (profile.grace_until - today).days if profile.grace_until else None

        return Response(
            {
                "business_id": business.id,
                "billing_exempt": billing_exempt,
                "billing_exempt_reason": getattr(business, "billing_exempt_reason", "") or "",
                "billing_exempt_until": getattr(business, "billing_exempt_until", None),
                "subscriptions_exempt": subs_exempt,
                "subscriptions_exempt_reason": getattr(business, "subscriptions_exempt_reason", "") or "",
                "subscriptions_exempt_until": getattr(business, "subscriptions_exempt_until", None),
                "stripe_setup_complete": True if billing_exempt else profile.stripe_setup_complete,
                "is_locked": profile.is_locked,
                "lock_reason": profile.lock_reason,
                "next_due_date": profile.next_due_date,
                "grace_until": profile.grace_until,
                "days_to_due": days_to_due,
                "days_to_lock": days_to_lock,
                "role": getattr(membership, "role", None),
                "card_brand": profile.card_brand,
                "card_last4": profile.card_last4,
                "card_exp_month": profile.card_exp_month,
                "card_exp_year": profile.card_exp_year,
                "days_to_card_expiry": profile.days_to_card_expiry(),
                "subscription_status": profile.subscription_status or "none",
                "subscription_cancel_at_period_end": bool(profile.subscription_cancel_at_period_end),
                "subscription_current_period_end": profile.subscription_current_period_end,
            }
        )


class CreateSetupCheckoutSessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        if _is_billing_exempt_now(business):
            return Response({"detail": "Billing exempt — no card required."}, status=200)

        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe authentication failed (check STRIPE_SECRET_KEY)."}, status=500)
        if not getattr(settings, "PLATFORM_BASE_URL", ""):
            return Response({"detail": "PLATFORM_BASE_URL is not configured."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)
        profile.ensure_due_dates()
        profile.save(update_fields=["next_due_date", "grace_until"])

        try:
            if not profile.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=getattr(request.user, "email", ""),
                    name=f"Business #{business.id}",
                    metadata={"business_id": str(business.id)},
                )
                profile.stripe_customer_id = customer["id"]
                profile.save(update_fields=["stripe_customer_id"])

            success_url = f"{settings.PLATFORM_BASE_URL}/upgrade?setup=success"
            cancel_url = f"{settings.PLATFORM_BASE_URL}/upgrade?setup=cancel"

            session = stripe.checkout.Session.create(
                mode="setup",
                customer=profile.stripe_customer_id,
                payment_method_types=["card"],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"business_id": str(business.id)},
            )

            return Response({"url": session["url"]})

        except stripe.error.AuthenticationError as e:
            return Response(
                {"detail": "Stripe authentication failed (check STRIPE_SECRET_KEY).", "error": str(e)},
                status=500,
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error while creating setup session.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error while creating setup session.", "error": str(e)}, status=500)


class BillingPreviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        billing_exempt = _is_billing_exempt_now(business)
        waive_subs = _is_subscriptions_exempt_now(business)

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)
        pricing = PlatformPricing()

        today = timezone.localdate()
        period_start = month_start(today)
        period_end = next_month_start(today) - timedelta(days=1)

        gross_paid_invoices_cents = _calc_paid_invoice_gross_cents(business.id, period_start, period_end)

        amounts = MonthlyPlatformBill.compute_amounts(
            profile=profile,
            pricing=pricing,
            gross_paid_invoices_cents=gross_paid_invoices_cents,
            waive_subscriptions=waive_subs,
        )

        if billing_exempt:
            amounts.update(
                {
                    "platform_fee_cents": 0,
                    "sbo_subscription_cents": 0,
                    "pm_subscription_cents": 0,
                    "seats_cents": 0,
                    "total_due_cents": 0,
                }
            )

        return Response(
            {
                "business_id": business.id,
                "billing_exempt": billing_exempt,
                "subscriptions_exempt": waive_subs,
                "period_start": period_start,
                "period_end": period_end,
                "seat_count": profile.seat_count(),
                "included_seats": pricing.included_seats,
                "extra_seats": profile.extra_seats(pricing),
                **amounts,
            }
        )


class CreateOrUpdateMonthlyBillAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        if _is_billing_exempt_now(business):
            return Response(
                {
                    "detail": "Billing exempt — no monthly bill created.",
                    "business_id": business.id,
                    "status": "EXEMPT",
                    "total_due_cents": 0,
                },
                status=200,
            )

        if not (
            _is_platform_admin(request.user)
            or business.owner_id == request.user.id
            or getattr(membership, "role", "") in ("OWNER", "MANAGER")
        ):
            return Response({"detail": "Not allowed."}, status=403)

        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe authentication failed (check STRIPE_SECRET_KEY)."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)
        if not profile.stripe_setup_complete or not profile.stripe_customer_id:
            return Response({"detail": "Card not on file. Complete billing setup first."}, status=400)

        pricing = PlatformPricing()

        today = timezone.localdate()
        period_start = month_start(today)
        period_end = next_month_start(today) - timedelta(days=1)

        bill, _ = MonthlyPlatformBill.objects.get_or_create(
            business=business,
            profile=profile,
            period_start=period_start,
            defaults={"period_end": period_end, "status": MonthlyPlatformBill.STATUS_DRAFT},
        )

        gross_paid_invoices_cents = _calc_paid_invoice_gross_cents(business.id, period_start, period_end)

        waive_subs = _is_subscriptions_exempt_now(business)
        amounts = MonthlyPlatformBill.compute_amounts(
            profile=profile,
            pricing=pricing,
            gross_paid_invoices_cents=gross_paid_invoices_cents,
            waive_subscriptions=waive_subs,
        )

        bill.period_end = period_end
        bill.gross_paid_invoices_cents = amounts["gross_paid_invoices_cents"]
        bill.platform_fee_cents = amounts["platform_fee_cents"]
        bill.sbo_subscription_cents = amounts["sbo_subscription_cents"]
        bill.pm_subscription_cents = amounts["pm_subscription_cents"]
        bill.seats_cents = amounts["seats_cents"]
        bill.total_due_cents = amounts["total_due_cents"]

        try:
            if not bill.stripe_invoice_id:

                def add_item(label: str, cents: int):
                    if cents <= 0:
                        return
                    stripe.InvoiceItem.create(
                        customer=profile.stripe_customer_id,
                        amount=int(cents),
                        currency="usd",
                        description=label,
                        metadata={"business_id": str(business.id), "period_start": str(period_start)},
                    )

                add_item("SyncWorks — SBO Subscription", bill.sbo_subscription_cents)
                add_item("SyncWorks — Property Management Subscription", bill.pm_subscription_cents)
                add_item("SyncWorks — Extra Seats", bill.seats_cents)
                add_item("SyncWorks — Platform Fee (1% of paid invoices)", bill.platform_fee_cents)

                inv = stripe.Invoice.create(
                    customer=profile.stripe_customer_id,
                    collection_method="charge_automatically",
                    auto_advance=True,
                    metadata={"business_id": str(business.id), "period_start": str(period_start)},
                    description=f"SyncWorks Monthly Bill ({period_start} → {period_end})",
                )
                bill.stripe_invoice_id = inv["id"]
                bill.status = MonthlyPlatformBill.STATUS_OPEN

        except Exception as e:
            bill.status = MonthlyPlatformBill.STATUS_FAILED
            bill.save()
            return Response({"detail": "Stripe invoice creation failed.", "error": str(e)}, status=500)

        bill.due_date = today + timedelta(days=7)
        bill.save()

        return Response(
            {
                "business_id": business.id,
                "period_start": bill.period_start,
                "period_end": bill.period_end,
                "status": bill.status,
                "stripe_invoice_id": bill.stripe_invoice_id,
                "gross_paid_invoices_cents": bill.gross_paid_invoices_cents,
                "platform_fee_cents": bill.platform_fee_cents,
                "sbo_subscription_cents": bill.sbo_subscription_cents,
                "pm_subscription_cents": bill.pm_subscription_cents,
                "seats_cents": bill.seats_cents,
                "total_due_cents": bill.total_due_cents,
                "subscriptions_exempt": _is_subscriptions_exempt_now(business),
            }
        )


class UnlockRequestAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        business_id = _get_business_id_from_request(request)
        if not business_id:
            return Response(
                {"detail": "Business context missing. Provide X-Business-Id header."},
                status=400,
            )

        title = (request.data.get("title") or "Unlock Request").strip()
        body = (request.data.get("body") or "").strip()

        if not body:
            body = "Please unlock my account. I updated billing / need help restoring access."

        role = getattr(request.user, "role", "") or ""

        existing = SupportRequest.objects.filter(
            kind=SupportRequest.Kind.UNLOCK,
            status=SupportRequest.Status.OPEN,
            business_id=business_id,
            requester=request.user,
        ).first()

        if existing:
            return Response(
                {"detail": "Unlock request already open.", "id": existing.id},
                status=200,
            )

        sr = SupportRequest.objects.create(
            requester=request.user,
            role=role,
            business_id=business_id,
            kind=SupportRequest.Kind.UNLOCK,
            title=title,
            body=body,
        )

        return Response({"detail": "Unlock request submitted.", "id": sr.id}, status=201)


class StripeWebhookAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe authentication not configured (STRIPE_SECRET_KEY)."}, status=500)

        if not getattr(settings, "STRIPE_WEBHOOK_SECRET", ""):
            return Response({"detail": "Stripe webhook not configured (STRIPE_WEBHOOK_SECRET)."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        payload = request.body
        sig_header = (
            request.META.get("HTTP_STRIPE_SIGNATURE")
            or request.headers.get("Stripe-Signature", "")
            or request.headers.get("stripe-signature", "")
            or ""
        )

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        except Exception:
            return Response({"detail": "Invalid signature."}, status=400)

        etype = event.get("type")
        data = event.get("data", {}).get("object", {}) or {}

        if etype == "checkout.session.completed":
            mode = data.get("mode")
            customer_id = data.get("customer")
            meta = data.get("metadata") or {}

            if mode == "setup":
                setup_intent = data.get("setup_intent")

                business_id = meta.get("business_id")
                if business_id and customer_id and setup_intent:
                    try:
                        si = stripe.SetupIntent.retrieve(setup_intent)
                        pm_id = si.get("payment_method")
                    except Exception:
                        pm_id = None

                    profile = PlatformBillingProfile.objects.filter(business_id=int(business_id)).first()
                    if profile:
                        profile.stripe_customer_id = customer_id or profile.stripe_customer_id

                        if pm_id:
                            profile.stripe_default_payment_method_id = pm_id
                            try:
                                stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id})
                            except Exception:
                                pass

                            try:
                                pm = stripe.PaymentMethod.retrieve(pm_id)
                                card = (pm.get("card") or {})
                                brand = card.get("brand") or ""
                                last4 = card.get("last4") or ""
                                exp_month = card.get("exp_month")
                                exp_year = card.get("exp_year")
                                profile.update_card_snapshot(
                                    brand=str(brand),
                                    last4=str(last4),
                                    exp_month=int(exp_month) if exp_month else None,
                                    exp_year=int(exp_year) if exp_year else None,
                                )
                            except Exception:
                                pass

                            profile.stripe_setup_complete = True

                            try:
                                profile.unlock()
                            except Exception:
                                pass

                        profile.save()

                user_id = meta.get("user_id")
                if user_id and customer_id and setup_intent:
                    try:
                        si = stripe.SetupIntent.retrieve(setup_intent)
                        pm_id = si.get("payment_method")
                    except Exception:
                        pm_id = None

                    uprof = UserBillingProfile.objects.filter(user_id=int(user_id)).first()
                    if uprof:
                        uprof.stripe_customer_id = customer_id or uprof.stripe_customer_id

                        if pm_id:
                            uprof.stripe_default_payment_method_id = pm_id
                            try:
                                stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id})
                            except Exception:
                                pass

                            try:
                                pm = stripe.PaymentMethod.retrieve(pm_id)
                                card = (pm.get("card") or {})
                                uprof.update_card_snapshot(
                                    brand=str(card.get("brand") or ""),
                                    last4=str(card.get("last4") or ""),
                                    exp_month=int(card.get("exp_month")) if card.get("exp_month") else None,
                                    exp_year=int(card.get("exp_year")) if card.get("exp_year") else None,
                                )
                            except Exception:
                                pass

                            uprof.stripe_setup_complete = True

                        uprof.save()

            if mode == "subscription":
                business_id = meta.get("business_id")
                subscription_id = data.get("subscription")

                if business_id and customer_id and subscription_id:
                    profile = PlatformBillingProfile.objects.filter(business_id=int(business_id)).first()
                    if profile:
                        profile.stripe_customer_id = customer_id or profile.stripe_customer_id
                        profile.stripe_subscription_id = str(subscription_id)

                        try:
                            sub = stripe.Subscription.retrieve(subscription_id)
                            _sync_subscription_snapshot(profile, sub)
                        except Exception:
                            profile.save(update_fields=["stripe_customer_id", "stripe_subscription_id"])

                        try:
                            profile.unlock()
                        except Exception:
                            pass

                        if profile.pk:
                            profile.refresh_from_db()

        if etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            customer_id = str(data.get("customer") or "").strip()
            if customer_id:
                profile = PlatformBillingProfile.objects.filter(stripe_customer_id=customer_id).first()
                if profile:
                    _sync_subscription_snapshot(profile, data)

                    status = str(data.get("status") or "").lower()
                    if status in ("active", "trialing"):
                        try:
                            profile.unlock()
                        except Exception:
                            pass
                        profile.save(update_fields=["is_locked", "locked_at", "lock_reason"])

        if etype == "account.updated":
            _sync_connect_snapshot_by_account_id(data)

        if etype == "invoice.paid":
            stripe_invoice_id = data.get("id")
            if stripe_invoice_id:
                bill = MonthlyPlatformBill.objects.filter(stripe_invoice_id=stripe_invoice_id).first()
                if bill:
                    bill.status = MonthlyPlatformBill.STATUS_PAID
                    bill.paid_at = timezone.now()
                    bill.save(update_fields=["status", "paid_at"])

                    prof = bill.profile
                    try:
                        prof.unlock()
                    except Exception:
                        pass
                    prof.save(update_fields=["is_locked", "locked_at", "lock_reason"])

        if etype == "invoice.payment_failed":
            stripe_invoice_id = data.get("id")
            if stripe_invoice_id:
                bill = MonthlyPlatformBill.objects.filter(stripe_invoice_id=stripe_invoice_id).first()
                if bill:
                    bill.status = MonthlyPlatformBill.STATUS_FAILED
                    bill.save(update_fields=["status"])

                    prof = bill.profile
                    try:
                        prof.lock("Payment failed. Update your billing method to regain access.")
                    except Exception:
                        pass
                    prof.save(update_fields=["is_locked", "locked_at", "lock_reason"])

                    try:
                        biz = Business.objects.filter(id=prof.business_id).first()
                        if biz:
                            recipients = _billing_recipient_user_ids(business=biz)
                            _notify_user_ids(
                                user_ids=recipients,
                                actor=None,
                                title="Payment failed — update billing",
                                body="Your payment failed. Please update your card on file to restore access.",
                                data={"business_id": biz.id, "type": "PAYMENT_FAILED"},
                            )
                            _create_platform_inbox_item(
                                requester=(biz.owner if hasattr(biz, "owner") else None),
                                business_id=biz.id,
                                kind=SupportRequest.Kind.BILLING,
                                title="[Billing] Payment failed — account locked",
                                body=(
                                    f"Business #{biz.id} ({getattr(biz, 'name', '')})\n\n"
                                    "Payment failed. Account was locked until billing is updated."
                                ),
                            )
                    except Exception:
                        pass

        return Response({"ok": True})