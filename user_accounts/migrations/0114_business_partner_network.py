import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import user_accounts.models.partner_network


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0113_master_projects_and_child_tickets"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessPartnerRelationship",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("relationship_type", models.CharField(choices=[("SUBCONTRACTOR", "Subcontractor"), ("VENDOR", "Vendor"), ("REFERRAL", "Referral partner"), ("JOINT_VENTURE", "Joint venture"), ("OVERFLOW", "Overflow provider"), ("PREFERRED", "Preferred service partner")], default="SUBCONTRACTOR", max_length=24)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACTIVE", "Active"), ("SUSPENDED", "Suspended"), ("DECLINED", "Declined"), ("TERMINATED", "Terminated")], db_index=True, default="PENDING", max_length=20)),
                ("preferred_partner", models.BooleanField(default=False)),
                ("default_markup_type", models.CharField(choices=[("NONE", "No default markup"), ("PERCENTAGE", "Percentage"), ("FIXED", "Fixed amount")], default="NONE", max_length=20)),
                ("default_markup_value", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("payment_terms_days", models.PositiveIntegerField(default=30)),
                ("insurance_verified", models.BooleanField(default=False)),
                ("license_verified", models.BooleanField(default=False)),
                ("compliance_notes", models.TextField(blank=True, default="")),
                ("internal_notes", models.TextField(blank=True, default="")),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accepted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_relationships_accepted", to=settings.AUTH_USER_MODEL)),
                ("hiring_business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partner_relationships_outbound", to="user_accounts.business")),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_relationships_invited", to=settings.AUTH_USER_MODEL)),
                ("partner_business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partner_relationships_inbound", to="user_accounts.business")),
                ("services_allowed", models.ManyToManyField(blank=True, related_name="partner_relationships", to="user_accounts.servicecategory")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="BusinessPartnerInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact_name", models.CharField(blank=True, default="", max_length=180)),
                ("email", models.EmailField(blank=True, db_index=True, default="", max_length=254)),
                ("phone", models.CharField(blank=True, default="", max_length=32)),
                ("business_name", models.CharField(blank=True, default="", max_length=180)),
                ("relationship_type", models.CharField(choices=[("SUBCONTRACTOR", "Subcontractor"), ("VENDOR", "Vendor"), ("REFERRAL", "Referral partner"), ("JOINT_VENTURE", "Joint venture"), ("OVERFLOW", "Overflow provider"), ("PREFERRED", "Preferred service partner")], default="SUBCONTRACTOR", max_length=24)),
                ("message", models.TextField(blank=True, default="")),
                ("token", models.CharField(default=user_accounts.models.partner_network._partner_invitation_token, editable=False, max_length=96, unique=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACCEPTED", "Accepted"), ("DECLINED", "Declined"), ("EXPIRED", "Expired"), ("CANCELLED", "Cancelled")], db_index=True, default="PENDING", max_length=20)),
                ("affiliate_code", models.CharField(blank=True, default="", max_length=32)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_invitations_created", to=settings.AUTH_USER_MODEL)),
                ("inviting_business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="partner_invitations_sent", to="user_accounts.business")),
                ("relationship", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invitation", to="user_accounts.businesspartnerrelationship")),
                ("target_business", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_invitations_received", to="user_accounts.business")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="businesspartnerrelationship",
            constraint=models.UniqueConstraint(fields=("hiring_business", "partner_business"), name="ua_unique_business_partner_pair"),
        ),
        migrations.AddConstraint(
            model_name="businesspartnerrelationship",
            constraint=models.CheckConstraint(condition=models.Q(("hiring_business", models.F("partner_business")), _negated=True), name="ua_partner_not_self"),
        ),
        migrations.AddIndex(
            model_name="businesspartnerrelationship",
            index=models.Index(fields=["hiring_business", "status", "updated_at"], name="ua_partner_out_status_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspartnerrelationship",
            index=models.Index(fields=["partner_business", "status", "updated_at"], name="ua_partner_in_status_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspartnerinvitation",
            index=models.Index(fields=["inviting_business", "status", "created_at"], name="ua_partner_invite_sent_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspartnerinvitation",
            index=models.Index(fields=["target_business", "status", "created_at"], name="ua_partner_invite_recv_idx"),
        ),
        migrations.AddIndex(
            model_name="businesspartnerinvitation",
            index=models.Index(fields=["email", "status", "created_at"], name="ua_partner_invite_email_idx"),
        ),
    ]
