from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("devices", "0013_ingress_debug")]

    operations = [
        migrations.AddField(
            model_name="edgenode",
            name="birth_metrics",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
