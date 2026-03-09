# backend/user_accounts/signals.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from user_accounts.models.business import Business
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.models.customer_settings import CustomerSettings

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
