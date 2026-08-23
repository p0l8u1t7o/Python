"""W5：StoragePlan.strategies 多選清單；既有資料遷移成 [strategy]。"""

from django.db import migrations, models


def seed_strategies(apps, schema_editor):
    StoragePlan = apps.get_model("ems", "StoragePlan")
    for plan in StoragePlan.objects.all():
        plan.strategies = [plan.strategy] if plan.strategy else []
        plan.save(update_fields=["strategies"])


class Migration(migrations.Migration):
    dependencies = [("ems", "0010_monthly_settlement")]

    operations = [
        migrations.AddField(
            model_name="storageplan",
            name="strategies",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_strategies, migrations.RunPython.noop),
    ]
