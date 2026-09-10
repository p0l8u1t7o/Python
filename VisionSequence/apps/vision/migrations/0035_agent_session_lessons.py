from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vision", "0034_dl_model_version")]
    operations = [migrations.AddField(model_name="agentsession", name="lessons", field=models.JSONField(default=dict, blank=True))]
