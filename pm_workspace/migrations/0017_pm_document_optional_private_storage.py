from django.db import migrations, models

import pm_workspace.private_document_storage


class Migration(migrations.Migration):
    dependencies = [
        ("pm_workspace", "0016_rename_pm_workspac_workspa_b98aec_idx_pm_workspac_workspa_7e7235_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pmpropertydocument",
            name="document",
            field=models.FileField(
                blank=True, null=True,
                storage=pm_workspace.private_document_storage.pm_document_storage,
                upload_to="pm/documents/%Y/%m/",
            ),
        ),
    ]
