# backend/user_accounts/signals.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from user_accounts.models.business import Business
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.models.customer_settings import CustomerSettings
from user_accounts.models.tickets import Ticket
from user_accounts.models.workforce import TicketOperationalProfile
from user_accounts.services.personal_calendar_sync import sync_ticket_to_personal_calendar

User = get_user_model()


@receiver(post_save, sender=Business)
def ensure_platform_billing_profile(sender, instance: Business, created: bool, **kwargs):
    if created:
        PlatformBillingProfile.objects.get_or_create(business=instance)


@receiver(post_save, sender=User)
def ensure_customer_settings(sender, instance: User, created: bool, **kwargs):
    """
    Guarantee every user has CustomerSettings for:
      - entitlements
      - profiles
      - notification prefs
      - calendar prefs
    """
    if created:
        CustomerSettings.objects.get_or_create(user=instance)


@receiver(post_save, sender=Ticket)
def keep_ticket_on_customer_calendar(sender, instance, **kwargs):
    sync_ticket_to_personal_calendar(instance)


@receiver(post_save, sender=TicketOperationalProfile)
def keep_operational_schedule_on_customer_calendar(sender, instance, **kwargs):
    sync_ticket_to_personal_calendar(instance.ticket)
