from rest_framework.routers import DefaultRouter

from .views import HouseholdGoalViewSet, HouseholdMemberSettingsViewSet, HouseholdProfileViewSet, MealPlanEntryViewSet, SharedTaskViewSet, ShoppingItemViewSet

router = DefaultRouter()
router.register("households", HouseholdProfileViewSet, basename="household")
router.register("member-settings", HouseholdMemberSettingsViewSet, basename="household-member-settings")
router.register("tasks", SharedTaskViewSet, basename="household-task")
router.register("shopping", ShoppingItemViewSet, basename="household-shopping")
router.register("goals", HouseholdGoalViewSet, basename="household-goal")
router.register("meals", MealPlanEntryViewSet, basename="household-meal")

urlpatterns = router.urls
