from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .business import Business


class ProfessionalPracticeProfile(models.Model):
    class PracticeType(models.TextChoices):
        DENTAL = "DENTAL", "Dentist / Dental practice"
        OPTOMETRY = "OPTOMETRY", "Optometrist / Eye care"
        CHIROPRACTIC = "CHIROPRACTIC", "Chiropractic"
        PHYSICAL_THERAPY = "PHYSICAL_THERAPY", "Physical therapy"
        VETERINARY = "VETERINARY", "Veterinary"
        MED_SPA = "MED_SPA", "Med spa"
        OTHER = "OTHER", "Other appointment business"

    business = models.OneToOneField(
        Business,
        related_name="professional_practice",
        on_delete=models.CASCADE,
    )
    practice_type = models.CharField(
        max_length=32,
        choices=PracticeType.choices,
        default=PracticeType.DENTAL,
        db_index=True,
    )
    scheduling_enabled = models.BooleanField(default=True)
    accepting_new_patients = models.BooleanField(default=True)
    accepted_insurance = models.JSONField(default=list, blank=True)
    appointment_types = models.JSONField(default=list, blank=True)
    weekly_schedule = models.JSONField(default=dict, blank=True)
    booking_lead_minutes = models.PositiveIntegerField(default=60)
    booking_buffer_minutes = models.PositiveIntegerField(default=0)
    scheduling_disclaimer = models.CharField(
        max_length=280,
        blank=True,
        default="Insurance participation is supplied by the practice. Confirm coverage with the practice or insurer before care.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["business__name"]

    def __str__(self) -> str:
        return f"{self.business.name} professional practice"


class ProfessionalAppointment(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        PROPOSED = "PROPOSED", "Proposed"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED", "Reschedule requested"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    business = models.ForeignKey(
        Business,
        related_name="professional_appointments",
        on_delete=models.CASCADE,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="professional_appointments",
        on_delete=models.CASCADE,
    )
    appointment_type = models.CharField(max_length=120, blank=True, default="Appointment")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    proposed_start = models.DateTimeField(null=True, blank=True)
    proposed_end = models.DateTimeField(null=True, blank=True)
    preferred_windows = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=240, blank=True, default="")
    insurance_plan = models.CharField(max_length=120, blank=True, default="")
    scheduling_note = models.TextField(blank=True, default="")
    reschedule_note = models.TextField(blank=True, default="")
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-proposed_start", "-created_at"]
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["customer", "status"]),
        ]

    def mark_response(self, new_status: str) -> None:
        self.status = new_status
        self.responded_at = timezone.now()
