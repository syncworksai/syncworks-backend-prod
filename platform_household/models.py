from __future__ import annotations

from django.conf import settings
from django.db import models

from platform_social.models import SocialGroup


class HouseholdProfile(models.Model):
    group = models.OneToOneField(SocialGroup, on_delete=models.CASCADE, related_name="household_profile")
    address_line1 = models.CharField(max_length=220, blank=True)
    address_line2 = models.CharField(max_length=220, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="US")
    timezone = models.CharField(max_length=64, default="America/Chicago")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="households_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class HouseholdMemberSettings(models.Model):
    household = models.ForeignKey(HouseholdProfile, on_delete=models.CASCADE, related_name="member_settings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_settings")
    share_calendar = models.BooleanField(default=True)
    share_tasks = models.BooleanField(default=True)
    share_shopping = models.BooleanField(default=True)
    share_meals = models.BooleanField(default=True)
    share_goals = models.BooleanField(default=True)
    share_finance_summary = models.BooleanField(default=False)
    share_finance_accounts = models.BooleanField(default=False)
    share_finance_bills = models.BooleanField(default=False)
    share_finance_income = models.BooleanField(default=False)
    share_finance_transactions = models.BooleanField(default=False)
    share_finance_budgets = models.BooleanField(default=False)
    availability_status = models.CharField(max_length=20, default="AVAILABLE")
    phone_available = models.BooleanField(default=True)
    computer_available = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("household", "user"), name="household_unique_member_settings")]


class SharedTask(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DONE = "DONE", "Done"
        SKIPPED = "SKIPPED", "Skipped"
        WEATHER_HOLD = "WEATHER_HOLD", "Weather hold"

    class Recurrence(models.TextChoices):
        NONE = "NONE", "Does not repeat"
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        MONTHLY = "MONTHLY", "Monthly"

    class WeatherStatus(models.TextChoices):
        NOT_CHECKED = "NOT_CHECKED", "Not checked"
        CLEAR = "CLEAR", "Weather clear"
        WATCH = "WATCH", "Weather watch"
        BLOCKED = "BLOCKED", "Weather blocked"

    household = models.ForeignKey(HouseholdProfile, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=180)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_tasks_created")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="household_tasks_assigned")
    due_at = models.DateTimeField(null=True, blank=True)
    estimated_minutes = models.PositiveSmallIntegerField(default=15)
    requires_phone = models.BooleanField(default=False)
    requires_computer = models.BooleanField(default=False)
    requires_focus = models.BooleanField(default=False)
    can_multitask = models.BooleanField(default=True)
    location_context = models.CharField(max_length=40, blank=True)
    recurrence = models.CharField(max_length=10, choices=Recurrence.choices, default=Recurrence.NONE)
    recurrence_interval = models.PositiveSmallIntegerField(default=1)
    weather_dependent = models.BooleanField(default=False)
    weather_status = models.CharField(max_length=16, choices=WeatherStatus.choices, default=WeatherStatus.NOT_CHECKED)
    weather_note = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "due_at", "id")


class ShoppingItem(models.Model):
    class Category(models.TextChoices):
        GROCERY = "GROCERY", "Grocery"
        HOUSEHOLD = "HOUSEHOLD", "Household"
        KIDS = "KIDS", "Kids"
        HEALTH = "HEALTH", "Health"
        HOME = "HOME", "Home"
        GIFTS = "GIFTS", "Gifts"
        OTHER = "OTHER", "Other"

    household = models.ForeignKey(HouseholdProfile, on_delete=models.CASCADE, related_name="shopping_items")
    name = models.CharField(max_length=180)
    quantity = models.CharField(max_length=40, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GROCERY)
    note = models.CharField(max_length=240, blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_shopping_added")
    is_checked = models.BooleanField(default=False)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="household_shopping_checked")
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("is_checked", "category", "name", "id")


class HouseholdGoal(models.Model):
    class Cadence(models.TextChoices):
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        MONTHLY = "MONTHLY", "Monthly"

    household = models.ForeignKey(HouseholdProfile, on_delete=models.CASCADE, related_name="goals")
    title = models.CharField(max_length=180)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_goals_created")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="household_goals_assigned")
    cadence = models.CharField(max_length=10, choices=Cadence.choices, default=Cadence.WEEKLY)
    target_value = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    current_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MealPlanEntry(models.Model):
    class MealType(models.TextChoices):
        BREAKFAST = "BREAKFAST", "Breakfast"
        LUNCH = "LUNCH", "Lunch"
        DINNER = "DINNER", "Dinner"
        SNACK = "SNACK", "Snack"

    household = models.ForeignKey(HouseholdProfile, on_delete=models.CASCADE, related_name="meal_plan")
    date = models.DateField()
    meal_type = models.CharField(max_length=12, choices=MealType.choices)
    title = models.CharField(max_length=180)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="household_meals_created")
    assigned_to = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="household_meal_assignments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date", "meal_type", "id")
