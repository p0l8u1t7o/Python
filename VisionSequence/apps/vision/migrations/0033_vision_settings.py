from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vision", "0032_flow_concurrency"),
    ]

    operations = [
        migrations.CreateModel(
            name="VisionSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("stable_cycle_mode", models.BooleanField(default=False)),
                ("log_level", models.CharField(default="info", max_length=10)),
                ("auto_save_enabled", models.BooleanField(default=False)),
                ("auto_save_interval_min", models.PositiveIntegerField(default=15)),
                ("last_auto_save_at", models.DateTimeField(blank=True, null=True)),
                ("last_auto_save_result", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
