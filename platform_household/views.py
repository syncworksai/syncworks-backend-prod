from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership, SocialGroup
from platform_social.views import MANAGEMENT_ROLES

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
        serializer.save()

    @action(detail=True, methods=["post"])
    def sync_members(self, request, pk=None):
        household = self.get_object()
        if not can_manage_household(request.user, household):
            return Response({"detail": "Only a Household manager can sync members."}, status=status.HTTP_403_FORBIDDEN)
        created = 0
        for member in GroupMembership.objects.filter(group=household.group, status=GroupMembership.Status.ACTIVE).select_related("user"):
            _, was_created = HouseholdMemberSettings.objects.get_or_create(household=household, user=member.user)
            created += int(was_created)
        return Response({"created": created})


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
        serializer.save()


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
        return SharedTask.objects.filter(household_id__in=active_household_ids(self.request.user)).select_related("created_by", "assigned_to")

    def perform_create(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to"))
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        household = self._household(serializer)
        ensure_assignee(household, serializer.validated_data.get("assigned_to", serializer.instance.assigned_to))
        status_value = serializer.validated_data.get("status", serializer.instance.status)
        completed_at = serializer.instance.completed_at
        if status_value == SharedTask.Status.DONE and not completed_at:
            completed_at = timezone.now()
        if status_value != SharedTask.Status.DONE:
            completed_at = None
        serializer.save(completed_at=completed_at)


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
