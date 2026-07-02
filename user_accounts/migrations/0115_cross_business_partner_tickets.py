import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0114_business_partner_network"),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerWorkTicket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("scope", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("OFFERED", "Offered"), ("ACCEPTED", "Accepted"), ("DECLINED", "Declined"), ("SCHEDULED", "Scheduled"), ("EN_ROUTE", "En route"), ("ON_SITE", "On site"), ("IN_PROGRESS", "In progress"), ("BLOCKED", "Blocked"), ("AWAITING_REVIEW", "Awaiting hiring-business review"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], db_index=True, default="OFFERED", max_length=24)),
                ("service_address", models.CharField(blank=True, default="", max_length=255)),
                ("service_zip", models.CharField(blank=True, default="", max_length=10)),
                ("access_instructions", models.TextField(blank=True, default="")),
                ("share_customer_contact", models.BooleanField(default=False)),
                ("customer_contact_name", models.CharField(blank=True, default="", max_length=180)),
                ("customer_contact_email", models.EmailField(blank=True, default="", max_length=254)),
                ("customer_contact_phone", models.CharField(blank=True, default="", max_length=32)),
                ("agreed_amount_cents", models.PositiveBigIntegerField(default=0)),
                ("partner_internal_cost_cents", models.PositiveBigIntegerField(default=0)),
                ("partner_internal_notes", models.TextField(blank=True, default="")),
                ("hiring_business_notes", models.TextField(blank=True, default="")),
                ("shared_updates", models.TextField(blank=True, default="")),
                ("completion_summary", models.TextField(blank=True, default="")),
                ("blocked_reason", models.TextField(blank=True, default="")),
                ("offered_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("declined_at", models.DateTimeField(blank=True, null=True)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accepted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_work_accepted", to=settings.AUTH_USER_MODEL)),
                ("assigned_member", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_work_assignments", to=settings.AUTH_USER_MODEL)),
                ("hiring_business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="partner_work_sent", to="user_accounts.business")),
                ("offered_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_work_offered", to=settings.AUTH_USER_MODEL)),
                ("partner_business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="partner_work_received", to="user_accounts.business")),
                ("relationship", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_tickets", to="user_accounts.businesspartnerrelationship")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_work_reviewed", to=settings.AUTH_USER_MODEL)),
                ("source_ticket", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="partner_work_ticket", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="partnerworkticket",
            index=models.Index(fields=["hiring_business", "status", "updated_at"], name="ua_pwork_hiring_status_idx"),
        ),
        migrations.AddIndex(
            model_name="partnerworkticket",
            index=models.Index(fields=["partner_business", "status", "updated_at"], name="ua_pwork_partner_status_idx"),
        ),
    ]
