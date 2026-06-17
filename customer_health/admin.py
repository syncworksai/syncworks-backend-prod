from __future__ import annotations

from django.contrib import admin

from .models import CustomerHealthProfile


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