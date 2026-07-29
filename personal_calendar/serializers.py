from rest_framework import serializers

from .models import PersonalCalendarEvent


class PersonalCalendarEventSerializer(serializers.ModelSerializer):
    audit_count = serializers.IntegerField(source="audit_entries.count", read_only=True)

    class Meta:
        model = PersonalCalendarEvent
        fields = (
            "id", "title", "description", "start_at", "end_at", "all_day", "timezone",
            "location_name", "address_line1", "address_line2", "city", "state",
            "postal_code", "country", "latitude", "longitude", "arrival_buffer_minutes",
            "reminder_minutes", "recurrence_rule", "source", "external_calendar_id",
            "external_event_id", "created_by_sync", "status", "metadata", "audit_count",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "created_by_sync", "audit_count", "created_at", "updated_at",
        )

    def validate(self, attrs):
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(self.instance, "end_at", None))
        if start_at and end_at and end_at < start_at:
            raise serializers.ValidationError({"end_at": "End time cannot be before start time."})
        return attrs
