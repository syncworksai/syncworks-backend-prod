from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def categorize_existing_groups(apps, schema_editor):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SocialGroup.objects.filter(kind__in=("TEAM", "CLUB")).update(category="SPORTS")
    SocialGroup.objects.filter(kind="HOUSEHOLD").update(category="FAMILY")


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0005_socialevent_flyer_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="category",
            field=models.CharField(
                choices=[
                    ("SPORTS", "Sports"),
                    ("FAMILY", "Family"),
                    ("WORK", "Work"),
                    ("HOBBIES", "Hobbies"),
                    ("CHURCH", "Church / Faith"),
                    ("FRIENDS", "Friends"),
                    ("COMMUNITY", "Community"),
                    ("OTHER", "Other"),
                ],
                default="COMMUNITY",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="socialgroup",
            name="allow_followers",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="UserPaymentProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cash_app_url", models.URLField(blank=True)),
                ("cash_app_label", models.CharField(blank=True, max_length=80)),
                ("venmo_url", models.URLField(blank=True)),
                ("venmo_label", models.CharField(blank=True, max_length=80)),
                ("zelle_instructions", models.CharField(blank=True, max_length=240)),
                ("stripe_payment_link", models.URLField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="social_payment_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="GroupFollow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="followers", to="platform_social.socialgroup")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_group_follows", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["group", "created_at"], name="social_follow_group_time"),
                    models.Index(fields=["user", "created_at"], name="social_follow_user_time"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("group", "user"), name="social_unique_group_follow"),
                ],
            },
        ),
        migrations.RunPython(categorize_existing_groups, migrations.RunPython.noop),
    ]
}
