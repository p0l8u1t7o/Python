from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vision", "0031_file_output_retention"),
    ]

    operations = [
        migrations.AddField(
            model_name="flow",
            name="concurrency",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
