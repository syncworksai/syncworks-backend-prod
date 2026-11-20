from django.urls import path
from .views import TechnicianShiftView

urlpatterns = [path("shift/", TechnicianShiftView.as_view(), name="technician-shift")]
