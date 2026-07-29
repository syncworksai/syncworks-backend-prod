from rest_framework.routers import DefaultRouter

from .views import PersonalCalendarEventViewSet

router = DefaultRouter()
router.register("events", PersonalCalendarEventViewSet, basename="personal-calendar-event")

urlpatterns = router.urls
