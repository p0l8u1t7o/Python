"""A5：流程層的逾時與判 NG 就停。"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("vision", "0029_dashboard")]

    operations = [
        migrations.AddField(
            model_name="flow",
            name="timeout_s",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="flow",
            name="stop_on_ng",
            field=models.BooleanField(default=False),
        ),
    ]
