"""BatchRun.flow：一次批次執行用哪個流程測（空＝影像集的流程），讓同一組影像可以測不同流程。"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vision", "0012_batchset_batchrun")]

    operations = [
        migrations.AddField(
            model_name="batchrun",
            name="flow",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="batch_runs", to="vision.flow"),
        ),
    ]
