from django.contrib import admin

from .models import PersonalCalendarEvent, PersonalCalendarEventAudit


@admin.register(PersonalCalendarEvent)
class PersonalCalendarEventAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "title", "start_at", "status", "source", "updated_at")
    list_filter = ("status", "source", "all_day", "created_by_sync")
    search_fields = ("title", "description", "location_name", "address_line1", "owner__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PersonalCalendarEventAudit)
class PersonalCalendarEventAuditAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "actor", "action", "created_at")
    list_filter = ("action",)
    search_fields = ("event__title", "actor__email")
    readonly_fields = ("created_at",)
