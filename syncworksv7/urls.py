from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),

    # Platform Growth
    path(
        "api/v1/platform-growth/",
        include("platform_growth.urls"),
    ),

    # Platform Affiliates
    path(
        "api/v1/platform-affiliates/",
        include("platform_affiliates.urls"),
    ),

    # Customer Health
    path(
        "api/v1/customer-health/",
        include("customer_health.urls"),
    ),

    # Main API
    path(
        "api/v1/",
        include("user_accounts.urls"),
    ),
]

# Dev media/static
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )

# Temporary production media serving
if not settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]