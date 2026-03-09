# backend/syncworksv7/urls.py
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    # ✅ Main API (everything lives under user_accounts.urls)
    path("api/v1/", include("user_accounts.urls")),
]

# ✅ Serve uploaded media in dev
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)