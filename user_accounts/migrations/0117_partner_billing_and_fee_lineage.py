import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import user_accounts.models.partner_billing


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0116_partner_estimates_and_change_orders"),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invoice_number", models.CharField(blank=True, default="", max_length=64)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("notes", models.TextField(blank=True, default="")),
                ("line_items", models.JSONField(blank=True, default=list)),
                ("subtotal_cents", models.PositiveBigIntegerField(default=0)),
                ("tax_cents", models.PositiveBigIntegerField(default=0)),
                ("total_cents", models.PositiveBigIntegerField(default=0)),
                ("amount_paid_cents", models.PositiveBigIntegerField(default=0)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("PARTIALLY_PAID", "Partially paid"), ("PAID", "Paid"), ("DISPUTED", "Disputed"), ("VOID", "Void")], db_index=True, default="DRAFT", max_length=24)),
                ("fee_treatment", models.CharField(choices=[("LINKED_SETTLEMENT", "Linked settlement — no duplicate platform fee"), ("INDEPENDENT_B2B", "Independent B2B transaction"), ("MANUAL_EXEMPT", "Manually exempt")], default="LINKED_SETTLEMENT", max_length=24)),
                ("fee_lineage_key", models.CharField(default=user_accounts.models.partner_billing._lineage_key, editable=False, max_length=64, unique=True)),
                ("platform_fee_rate_bps", models.PositiveIntegerField(default=100)),
                ("platform_fee_amount_cents", models.PositiveBigIntegerField(default=0)),
                ("processor_fee_amount_cents", models.PositiveBigIntegerField(default=0)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("disputed_at", models.DateTimeField(blank=True, null=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_invoices_approved", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_invoices_created", to=settings.AUTH_USER_MODEL)),
                ("issuing_business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="partner_invoices_issued", to="user_accounts.business")),
                ("paying_business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="partner_invoices_payable", to="user_accounts.business")),
                ("work_ticket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="partner_invoices", to="user_accounts.partnerworkticket")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PartnerPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_cents", models.PositiveBigIntegerField()),
                ("method", models.CharField(choices=[("CREDIT_CARD", "Credit card"), ("DEBIT_CARD", "Debit card"), ("ACH", "ACH"), ("STRIPE", "Stripe"), ("CASH", "Cash"), ("CHECK", "Check"), ("ZELLE", "Zelle"), ("CASH_APP", "Cash App"), ("VENMO", "Venmo"), ("BANK_TRANSFER", "Bank transfer"), ("OTHER", "Other")], default="ACH", max_length=24)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("CONFIRMED", "Confirmed"), ("FAILED", "Failed"), ("REFUNDED", "Refunded"), ("VOID", "Void")], db_index=True, default="PENDING", max_length=20)),
                ("processor_fee_amount_cents", models.PositiveBigIntegerField(default=0)),
                ("external_reference", models.CharField(blank=True, default="", max_length=255)),
                ("receipt_url", models.URLField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("stripe_payment_intent_id", models.CharField(blank=True, default="", max_length=255)),
                ("stripe_charge_id", models.CharField(blank=True, default="", max_length=255)),
                ("stripe_transfer_id", models.CharField(blank=True, default="", max_length=255)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_payments_confirmed", to=settings.AUTH_USER_MODEL)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="user_accounts.partnerinvoice")),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_payments_recorded", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-recorded_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PartnerPaymentAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("allocated_amount_cents", models.PositiveBigIntegerField(default=0)),
                ("lineage_key", models.CharField(db_index=True, max_length=64)),
                ("platform_fee_already_assessed", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("customer_invoice", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_payment_allocations", to="user_accounts.invoice")),
                ("partner_payment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="user_accounts.partnerpayment")),
                ("source_ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_payment_allocations", to="user_accounts.ticket")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddIndex(model_name="partnerinvoice", index=models.Index(fields=["issuing_business", "status", "created_at"], name="ua_b2binv_issuer_status_idx")),
        migrations.AddIndex(model_name="partnerinvoice", index=models.Index(fields=["paying_business", "status", "due_date"], name="ua_b2binv_payer_status_idx")),
        migrations.AddIndex(model_name="partnerinvoice", index=models.Index(fields=["work_ticket", "status", "created_at"], name="ua_b2binv_work_status_idx")),
        migrations.AddIndex(model_name="partnerpayment", index=models.Index(fields=["invoice", "status", "recorded_at"], name="ua_b2bpay_invoice_status_idx")),
        migrations.AddIndex(model_name="partnerpayment", index=models.Index(fields=["method", "status", "recorded_at"], name="ua_b2bpay_method_status_idx")),
        migrations.AddIndex(model_name="partnerpaymentallocation", index=models.Index(fields=["lineage_key", "created_at"], name="ua_b2balloc_lineage_idx")),
    ]
