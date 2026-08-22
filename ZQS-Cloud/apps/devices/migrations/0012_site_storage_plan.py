# Step 2 of the plan-template migration: the binding lives on the site.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0011_merge_generation_blueprints"),
        ("ems", "0007_plan_templates_step1"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="storage_plan",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sites",
                to="ems.storageplan",
            ),
        ),
    ]
