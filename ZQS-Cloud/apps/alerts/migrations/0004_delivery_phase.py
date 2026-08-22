from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("alerts", "0003_line_and_event_notifications")]

    operations = [
        migrations.AddField(
            model_name="notificationdelivery",
            name="phase",
            field=models.CharField(
                choices=[("raised", "Raised"), ("resolved", "Resolved")],
                default="raised",
                max_length=10,
            ),
        ),
    ]
