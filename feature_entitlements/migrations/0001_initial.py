from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "__first__"),
    ]
    operations = [
        migrations.CreateModel(
            name="BusinessFeatureEntitlement",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("feature", models.CharField(max_length=48, choices=[(x,x) for x in ("business_jarvis","ai_assistant","technician_tracking","ai_weather","ai_traffic","smart_routes","automated_email","ai_phone")])),
                ("state", models.CharField(max_length=16, default="OFF", choices=[("OFF","Off"),("TRIAL","Trial"),("PAID","Paid"),("OVERRIDE","Admin override")])),
                ("trial_started_at", models.DateTimeField(null=True, blank=True)),
                ("trial_expires_at", models.DateTimeField(null=True, blank=True)),
                ("paid_through", models.DateTimeField(null=True, blank=True)),
                ("override_expires_at", models.DateTimeField(null=True, blank=True)),
                ("override_reason", models.CharField(max_length=300, blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feature_entitlements", to="user_accounts.business")),
                ("modified_by", models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="BusinessAIBudget",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("period", models.CharField(max_length=7)),
                ("reserved_cents", models.PositiveIntegerField(default=0)),
                ("spent_cents", models.PositiveIntegerField(default=0)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_budgets", to="user_accounts.business")),
            ],
        ),
        migrations.AddConstraint(model_name="businessfeatureentitlement",constraint=models.UniqueConstraint(fields=("business","feature"),name="unique_business_feature_entitlement")),
        migrations.AddConstraint(model_name="businessaibudget",constraint=models.UniqueConstraint(fields=("business","period"),name="unique_business_ai_month")),
    ]
