from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("vision", "0037_engineering_note")]

    operations = [
        migrations.CreateModel(
            name="InspectionTrial",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("graph_hash", models.TextField()),
                ("readings", models.JSONField(default=list)),
                ("status", models.CharField(max_length=8)),
                ("judge", models.CharField(blank=True, max_length=200)),
                ("executed_at", models.DateTimeField()),
                ("executed_by", models.CharField(max_length=150)),
                ("flow", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inspection_trial", to="vision.flow")),
            ],
        ),
    ]
