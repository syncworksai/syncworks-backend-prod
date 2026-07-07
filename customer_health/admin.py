from __future__ import annotations

from django.contrib import admin

from .models import CustomerHealthFeedback, CustomerHealthProfile


@admin.register(CustomerHealthProfile)
class CustomerHealthProfileAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "user__email",
        "user__username",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
    ]


@admin.register(CustomerHealthFeedback)
class CustomerHealthFeedbackAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "area",
        "severity",
        "status",
        "created_at",
    ]
    list_filter = [
        "status",
        "severity",
        "area",
        "created_at",
    ]
    search_fields = [
        "user__email",
        "user__username",
        "message",
        "area",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
    ]
