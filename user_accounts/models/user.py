# backend/user_accounts/models/user.py
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    SyncWorks custom user model.

    Everyone starts as CUSTOMER.
    Platform owners (you) get is_platform_admin=True.
    """

    ROLE_CHOICES = (
        ("CUSTOMER", "Customer"),
        ("SBO", "Small Business Owner"),
        ("SUB", "Subcontractor"),
        ("EMPLOYEE", "Employee"),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="CUSTOMER",
    )

    # GOD MODE / PLATFORM OWNER
    is_platform_admin = models.BooleanField(
        default=False,
        help_text="SyncWorks internal platform admin (God Mode)",
    )

    def __str__(self):
        return self.username or self.email or f"User#{self.pk}"
