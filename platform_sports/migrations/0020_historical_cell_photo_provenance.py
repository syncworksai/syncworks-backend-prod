from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0019_link_verified_bed_springs_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="softballplateappearance",
            name="source_photo",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="transcribed_plays", to="platform_sports.sportsgamebookphoto",
            ),
        ),
        migrations.AddField(
            model_name="softballplateappearance",
            name="source_cell_key",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddConstraint(
            model_name="softballplateappearance",
            constraint=models.UniqueConstraint(
                fields=("source_photo", "source_cell_key"),
                condition=Q(source_photo__isnull=False) & ~Q(source_cell_key=""),
                name="sports_unique_source_cell",
            ),
        ),
    ]
