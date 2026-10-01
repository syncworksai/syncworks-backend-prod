import calendar
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from personal_calendar.models import PersonalCalendarEvent
from platform_social.models import GroupMembership, SocialGroup
from platform_social.views import MANAGEMENT_ROLES
from user_accounts.models.personal_finance import FinanceAccount, FinanceBudget, FinanceLiability, FinanceObligation
from user_accounts.services.finance_intelligence import build_debt_plan_1, build_finance_briefing

from .models import HouseholdGoal, HouseholdMemberSettings, HouseholdProfile, MealPlanEntry, SharedTask, ShoppingItem
from .serializers import HouseholdGoalSerializer, HouseholdMemberSettingsSerializer, HouseholdProfileSerializer, MealPlanEntrySerializer, SharedTaskSerializer, ShoppingItemSerializer


def active_household_ids(user):
    group_ids = GroupMembership.objects.filter(user=user, status=GroupMembership.Status.ACTIVE).values_list("group_id", flat=True)
    return HouseholdProfile.objects.filter(group_id__in=group_ids).values_list("id", flat=True)


def can_manage_household(user, household):
    return GroupMembership.objects.filter(
        group=household.group,
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).exists()


def is_active_member(user, household):
    return GroupMembership.objects.filter(group=household.group, user=user, status=GroupMembership.Status.ACTIVE).exists()


def ensure_assignee(household, user):
    if user and not is_active_member(user, household):
        raise serializers.ValidationError("Assignee must be an active Household member.")


def recurrence_rule(task):
    interval = max(int(task.recurrence_interval or 1), 1)
    if task.recurrence == SharedTask.Recurrence.DAILY:
        return f"RRULE:FREQ=DAILY;INTERVAL={interval}"
    if task.recurrence == SharedTask.Recurrence.WEEKLY:
        return f"RRULE:FREQ=WEEKLY;INTERVAL={interval}"
    if task.recurrence == SharedTask.Recurrence.MONTHLY:
        return f"RRULE:FREQ=MONTHLY;INTERVAL={interval}"
    return ""


def next_due_at(task):
    if not task.due_at or task.recurrence == SharedTask.Recurrence.NONE:
        return None
    interval = max(int(task.recurrence_interval or 1), 1)
    if task.recurrence == SharedTask.Recurrence.DAILY:
        return task.due_at + timedelta(days=interval)
    if task.recurrence == SharedTask.Recurrence.WEEKLY:
        return task.due_at + timedelta(weeks=interval)
    if task.recurrence == SharedTask.Recurrence.MONTHLY:
        current = task.due_at
        month_index = current.month - 1 + interval
        year = current.year + month_index // 12
        month = month_index % 12 + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    return None


def calendar_description(task):
    parts = [task.notes.strip()] if task.notes.strip() else []
    if task.weather_dependent:
        parts.append("Weather permitting")
        if task.weather_note:
            parts.append(task.weather_note)
    return "\n".join(parts)


def sync_task_to_household_calendars(task):
    if not task.due_at:
        return
    household = task.household
    settings_qs = HouseholdMemberSettings.objects.filter(
        household=household,
        share_calendar=True,
        share_tasks=True,
    ).select_related("user")
    active_user_ids = set(
        GroupMembership.objects.filter(
            group=household.group,
            status=GroupMembership.Status.ACTIVE,
        ).values_list("user_id", flat=True)
    )
    desired_owner_ids = set()
    for member_settings in settings_qs:
        if member_settings.user_id not in active_user_ids:
            continue
        desired_owner_ids.add(member_settings.user_id)
        defaults = {
            "title": task.title,
            "description": calendar_description(task),
            "start_at": task.due_at,
            "end_at": task.due_at + timedelta(minutes=max(int(task.estimated_minutes or 15), 1)),
            "timezone": household.timezone,
            "location_name": "Household task",
            "address_line1": household.address_line1,
            "address_line2": household.address_line2,
            "city": household.city,
            "state": household.state,
            "postal_code": household.postal_code,
            "country": household.country,
            "recurrence_rule": recurrence_rule(task),
            "source": PersonalCalendarEvent.Source.SYNC,
            "created_by_sync": True,
            "status": PersonalCalendarEvent.Status.ACTIVE if task.status != SharedTask.Status.DONE else PersonalCalendarEvent.Status.ARCHIVED,
            "metadata": {
                "household_id": household.id,
                "household_task_id": task.id,
                "weather_dependent": task.weather_dependent,
                "weather_status": task.weather_status,
                "household_task_status": task.status,
            },
        }
        existing = PersonalCalendarEvent.objects.filter(
            owner=member_settings.user,
            source=PersonalCalendarEvent.Source.SYNC,
            metadata__household_task_id=task.id,
        ).first()
        if existing:
            for field, value in defaults.items():
                setattr(existing, field, value)
            existing.save()
        else:
            PersonalCalendarEvent.objects.create(owner=member_settings.user, **defaults)

    PersonalCalendarEvent.objects.filter(
        source=PersonalCalendarEvent.Source.SYNC,
        metadata__household_task_id=task.id,
    ).exclude(owner_id__in=desired_owner_ids).update(status=PersonalCalendarEvent.Status.ARCHIVED)


def create_next_recurring_task(task):
    next_due = next_due_at(task)
    if not next_due:
        return None
    next_task = SharedTask.objects.create(
        household=task.household,
        title=task.title,
        notes=task.notes,
        created_by=task.created_by,
        assigned_to=task.assigned_to,
        due_at=next_due,
        estimated_minutes=task.estimated_minutes,
        requires_phone=task.requires_phone,
        requires_computer=task.requires_computer,
        requires_focus=task.requires_focus,
        can_multitask=task.can_multitask,
        location_context=task.location_context,
        recurrence=task.recurrence,
        recurrence_interval=task.recurrence_interval,
        weather_dependent=task.weather_dependent,
        weather_status=SharedTask.WeatherStatus.NOT_CHECKED,
        weather_note="",
        status=SharedTask.Status.OPEN,
    )
    sync_task_to_household_calendars(next_task)
    return next_task


class HouseholdProfileViewSet(viewsets.ModelViewSet):
    serializer_class = HouseholdProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return HouseholdProfile.objects.filter(id__in=active_household_ids(self.request.user)).select_related("group", "created_by").prefetch_related("member_settings__user")

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        membership = GroupMembership.objects.filter(group=group, user=self.request.user, status=GroupMembership.Status.ACTIVE, role__in=MANAGEMENT_ROLES).first()
        if group.kind != SocialGroup.Kind.HOUSEHOLD or not membership:
            raise serializers.ValidationError("You must manage an explicit HOUSEHOLD group to activate Household coordination.")
        with transaction.atomic():
            household = serializer.save(created_by=self.request.user)
            for member in GroupMembership.objects.filter(group=group, status=GroupMembership.Status.ACTIVE).select_related("user"):
                HouseholdMemberSettings.objects.get_or_create(household=household, user=member.user)

    def perform_update(self, serializer):
        household = self.get_object()
        if not can_manage_household(self.request.user, household):
            raise serializers.ValidationError("Only a Household manager can edit the Household profile.")
        household = serializer.save()
        for task in household.tasks.exclude(status=SharedTask.Status.DONE):
            sync_task_to_household_calendars(task)

    @action(detail=True, methods=["post"])
    def sync_members(self, request, pk=None):
        household = self.get_object()
        if not can_manage_household(request.user, household):
            return Response({"detail": "Only a Household manager can sync members."}, status=status.HTTP_403_FORBIDDEN)
        created = 0
        for member in GroupMembership.objects.filter(group=household.group, status=GroupMembership.Status.ACTIVE).select_related("user"):
            _, was_created = HouseholdMemberSettings.objects.get_or_create(household=household, user=member.user)
            created += int(was_created)
        for task in household.tasks.exclude(status=SharedTask.Status.DONE):
            sync_task_to_household_calendars(task)
        return Response({"created": created})

    @action(detail=True, methods=["get"], url_path="finance")
    def finance(self, request, pk=None):
        """Privacy-aware household finance summary.

        Finance records remain owned by the individual user. This endpoint only
        combines another member's data when that member explicitly enabled the
        corresponding Household sharing permission.
        """
        household = self.get_object()
        try:
            extra_monthly = max(Decimal("0"), Decimal(str(request.query_params.get("extra_monthly") or "0")))
        except (InvalidOperation, TypeError, ValueError):
            extra_monthly = Decimal("0")

        memberships = list(
            GroupMembership.objects.filter(
                group=household.group,
                status=GroupMembership.Status.ACTIVE,
            ).select_related("user")
        )
        settings_by_user = {}
        for membership in memberships:
            settings_obj, _ = HouseholdMemberSettings.objects.get_or_create(
                household=household,
                user=membership.user,
            )
            settings_by_user[membership.user_id] = settings_obj

        owner_labels = {}
        members_payload = []
        plan_liabilities = []
        total_debt = Decimal("0")
        total_cash = Decimal("0")
        total_minimums = Decimal("0")
        total_due = Decimal("0")
        total_income = Decimal("0")
        total_spending = Decimal("0")
        shared_summary_members = 0
        ai_plan_members = 0

        for membership in memberships:
            member = membership.user
            member_settings = settings_by_user[member.id]
            display_name = (
                f"{getattr(member, 'first_name', '')} {getattr(member, 'last_name', '')}".strip()
                or getattr(member, "email", "")
                or f"Member {member.id}"
            )
            owner_labels[member.id] = display_name
            is_self = member.id == request.user.id

            share_summary = is_self or member_settings.share_finance_summary
            share_accounts = is_self or member_settings.share_finance_accounts
            share_bills = is_self or member_settings.share_finance_bills
            share_income = is_self or member_settings.share_finance_income
            share_transactions = is_self or member_settings.share_finance_transactions
            share_budgets = is_self or member_settings.share_finance_budgets
            share_with_ai = is_self or (
                member_settings.share_finance_summary
                and member_settings.share_finance_with_ai
            )

            briefing = build_finance_briefing(member) if (
                share_summary or share_income or share_transactions
            ) else None
            visible_summary = {}
            if briefing and share_summary:
                source = briefing["summary"]
                visible_summary.update({
                    "available_cash": source["available_cash"],
                    "total_debt": source["total_debt"],
                    "known_minimum_payments": source["known_minimum_payments"],
                    "credit_utilization_percent": source["credit_utilization_percent"],
                })
                total_cash += source["available_cash"] or Decimal("0")
                total_debt += source["total_debt"] or Decimal("0")
                total_minimums += source["known_minimum_payments"] or Decimal("0")
                shared_summary_members += 1
            if briefing and share_bills:
                visible_summary["known_30_day_obligations"] = briefing["summary"]["known_30_day_obligations"]
                total_due += briefing["summary"]["known_30_day_obligations"] or Decimal("0")
            if briefing and share_income:
                visible_summary["month_income"] = briefing["summary"]["month_income"]
                total_income += briefing["summary"]["month_income"] or Decimal("0")
            if briefing and share_transactions:
                visible_summary["month_spending"] = briefing["summary"]["month_spending"]
                total_spending += briefing["summary"]["month_spending"] or Decimal("0")

            details = {}
            if share_accounts:
                details["accounts"] = list(
                    FinanceAccount.objects.filter(user=member, is_hidden=False)
                    .values("id", "name", "kind", "mask", "current_balance", "available_balance", "credit_limit", "is_manual")
                )
            if share_bills:
                details["obligations"] = list(
                    FinanceObligation.objects.filter(user=member, active=True)
                    .values("id", "name", "category", "expected_amount", "minimum_amount", "next_due_date", "autopay", "cadence")
                )
                details["debt_payments"] = list(
                    FinanceLiability.objects.filter(user=member, outstanding_balance__gt=0)
                    .values("id", "name", "kind", "minimum_payment", "next_payment_amount", "next_payment_date")
                )
            if share_budgets:
                details["budgets"] = list(
                    FinanceBudget.objects.filter(user=member, active=True)
                    .values("id", "name", "category", "monthly_limit", "priority")
                )
            if share_transactions and briefing:
                details["spending_by_category"] = briefing["top_spending_categories"]

            if share_with_ai:
                member_debts = list(
                    FinanceLiability.objects.filter(
                        user=member,
                        outstanding_balance__gt=0,
                    ).select_related("account")
                )
                plan_liabilities.extend(member_debts)
                ai_plan_members += 1

            members_payload.append({
                "user_id": member.id,
                "display_name": display_name,
                "is_self": is_self,
                "privacy_status": "MY_FINANCE" if is_self else ("SHARED" if share_summary else "PRIVATE"),
                "sharing": {
                    "summary": member_settings.share_finance_summary,
                    "accounts": member_settings.share_finance_accounts,
                    "bills": member_settings.share_finance_bills,
                    "income": member_settings.share_finance_income,
                    "transactions": member_settings.share_finance_transactions,
                    "budgets": member_settings.share_finance_budgets,
                    "with_ai": member_settings.share_finance_with_ai,
                },
                "summary": visible_summary if visible_summary else None,
                "details": details,
            })

        plan_1 = build_debt_plan_1(
            plan_liabilities,
            extra_monthly=extra_monthly,
            owner_labels=owner_labels,
        )

        return Response({
            "household": {
                "id": household.id,
                "name": household.group.name,
            },
            "summary": {
                "visible_total_debt": total_debt,
                "visible_available_cash": total_cash,
                "visible_known_minimum_payments": total_minimums,
                "visible_30_day_obligations": total_due,
                "visible_month_income": total_income,
                "visible_month_spending": total_spending,
                "shared_summary_members": shared_summary_members,
                "active_members": len(memberships),
                "ai_plan_members": ai_plan_members,
            },
            "plan_1": plan_1,
            "members": members_payload,
            "privacy_note": "Each finance record stays owned by its user. Household totals only include data that user chose to share; your own data is always visible to you.",
        })


class HouseholdMemberSettingsViewSet(viewsets.ModelViewSet):
    serializer_class = HouseholdMemberSettingsSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        household_ids = list(active_household_ids(self.request.user))
        for household in HouseholdProfile.objects.filter(id__in=household_ids):
            HouseholdMemberSettings.objects.get_or_create(household=household, user=self.request.user)
        return HouseholdMemberSettings.objects.filter(household_id__in=household_ids).select_related("user", "household__group")

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.user_id != self.request.user.id:
            raise serializers.ValidationError("Only the member can change their own sharing permissions.")
        updated = serializer.save()
        for task in updated.household.tasks.exclude(status=SharedTask.Status.DONE):
            sync_task_to_household_calendars(task)


class HouseholdScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def _household(self, serializer):
        household = serializer.validated_data.get("household") or getattr(self.get_object(), "household", None)
        if not household or not is_active_member(self.request.user, household):
            raise serializers.ValidationError("You must be an active member of this Household.")
        return household


class SharedTaskViewSet(HouseholdScopedViewSet):
    serializer_class = SharedTaskSerializer

    def get_queryset(self):
        return SharedTask.objects.filter(household_id__in=active_household_ids(self.request.user)).select_related("created_by", "assigned_to", "household__group")

    def perform_create(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to"))
        task = serializer.save(created_by=self.request.user)
        sync_task_to_household_calendars(task)

    def perform_update(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to", serializer.instance.assigned_to))
        original_status = serializer.instance.status
        status_value = serializer.validated_data.get("status", original_status)
        completed_at = serializer.instance.completed_at
        if status_value == SharedTask.Status.DONE and not completed_at:
            completed_at = timezone.now()
        if status_value != SharedTask.Status.DONE:
            completed_at = None
        task = serializer.save(completed_at=completed_at)
        sync_task_to_household_calendars(task)
        if original_status != SharedTask.Status.DONE and task.status == SharedTask.Status.DONE:
            create_next_recurring_task(task)


class ShoppingItemViewSet(HouseholdScopedViewSet):
    serializer_class = ShoppingItemSerializer

    def get_queryset(self):
        return ShoppingItem.objects.filter(household_id__in=active_household_ids(self.request.user)).select_related("added_by", "checked_by")

    def perform_create(self, serializer):
        self._household(serializer)
        serializer.save(added_by=self.request.user)

    def perform_update(self, serializer):
        self._household(serializer)
        checked = serializer.validated_data.get("is_checked", serializer.instance.is_checked)
        serializer.save(checked_by=self.request.user if checked else None, checked_at=timezone.now() if checked else None)


class HouseholdGoalViewSet(HouseholdScopedViewSet):
    serializer_class = HouseholdGoalSerializer

    def get_queryset(self):
        return HouseholdGoal.objects.filter(household_id__in=active_household_ids(self.request.user)).select_related("created_by", "assigned_to")

    def perform_create(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to"))
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to", serializer.instance.assigned_to))
        serializer.save()


class MealPlanEntryViewSet(HouseholdScopedViewSet):
    serializer_class = MealPlanEntrySerializer

    def get_queryset(self):
        return MealPlanEntry.objects.filter(household_id__in=active_household_ids(self.request.user)).prefetch_related("assigned_to")

    def perform_create(self, serializer):
        self._household(serializer)
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._household(serializer)
        serializer.save()
