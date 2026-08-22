# Storage plans become named templates. Step 1: add the name column while the
# site column still exists, so step 3 can migrate data between them.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ems", "0006_strategies_and_demand_response"),
    ]

    operations = [
        migrations.AddField(
            model_name="storageplan",
            name="name",
            field=models.CharField(default="", max_length=120),
            preserve_default=False,
        ),
    ]
