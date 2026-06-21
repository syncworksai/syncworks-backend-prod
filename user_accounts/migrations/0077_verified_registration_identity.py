from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def mark_existing_users_verified(apps, schema_editor):
    """
    Preserve every account created before verified registration launched.

    New accounts are created with email_verified=False until the
    registration flow explicitly verifies the email.
    """
    User = apps.get_model("user_accounts", "User")

    User.objects.filter(email_verified=False).update(
        email_verified=True,
        email_verified_at=timezone.now(),
    )


def reverse_existing_user_verification(apps, schema_editor):
    """
    No destructive reverse operation.

    Reversing this data step must not unexpectedly unverify existing users.
    """
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("platform_affiliates", "0002_agreement_templates"),
        ("user_accounts", "0076_service_request_intake_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verified_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="is_test_account",
            field=models.BooleanField(
                default=False,
                help_text="Marks an approved internal testing account.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="registration_source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("WEB", "Web"),
                    ("INVITATION", "Invitation"),
                    ("COLLECTION", "Collection"),
                    ("BUSINESS", "Business"),
                    ("FAMILY", "Family"),
                    ("INTERNAL", "Internal"),
                ],
                default="WEB",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="registration_promo_code",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="affiliate_referral_code",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="affiliate_attributed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="referred_by_affiliate",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="referred_users",
                to="platform_affiliates.affiliatepartner",
            ),
        ),
        migrations.CreateModel(
            name="EmailVerificationChallenge",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "public_id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        db_index=True,
                        max_length=254,
                    ),
                ),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("REGISTER", "Register"),
                            (
                                "VERIFY_EXISTING",
                                "Verify existing email",
                            ),
                            (
                                "PASSWORD_RESET",
                                "Password reset",
                            ),
                            (
                                "CHANGE_EMAIL",
                                "Change email",
                            ),
                        ],
                        db_index=True,
                        default="REGISTER",
                        max_length=32,
                    ),
                ),
                (
                    "code_hash",
                    models.CharField(
                        max_length=255,
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        db_index=True,
                    ),
                ),
                (
                    "verified_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "consumed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "attempt_count",
                    models.PositiveSmallIntegerField(
                        default=0,
                    ),
                ),
                (
                    "resend_count",
                    models.PositiveSmallIntegerField(
                        default=0,
                    ),
                ),
                (
                    "last_sent_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "requested_ip",
                    models.GenericIPAddressField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "user_agent",
                    models.TextField(
                        blank=True,
                        default="",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["email", "purpose"],
                        name="ua_verify_email_purpose_idx",
                    ),
                    models.Index(
                        fields=["expires_at"],
                        name="ua_verify_expires_idx",
                    ),
                    models.Index(
                        fields=["created_at"],
                        name="ua_verify_created_idx",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            mark_existing_users_verified,
            reverse_existing_user_verification,
        ),
    ]