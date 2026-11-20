from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("user_accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="TechnicianShift",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("clock_in_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("clock_out_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="technician_shifts", to="user_accounts.business")),
                ("technician", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="technician_shifts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["-clock_in_at"]},
        ),
        migrations.AddConstraint(model_name="technicianshift", constraint=models.UniqueConstraint(condition=Q(clock_out_at__isnull=True), fields=("business","technician"), name="one_active_tech_shift_per_business")),
    ]
