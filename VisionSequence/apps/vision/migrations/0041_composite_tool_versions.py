# 複合工具版本鎖定（PRODUCT-DIRECTION v2 P5）：CompositeTool.version 與每一版的快照；既有工具補一筆 v1 快照

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_snapshots(apps, schema_editor):
    CompositeTool = apps.get_model("vision", "CompositeTool")
    CompositeToolVersion = apps.get_model("vision", "CompositeToolVersion")
    for row in CompositeTool.objects.select_related("flow").all():
        CompositeToolVersion.objects.get_or_create(
            tool=row, version=row.version or 1,
            defaults={"graph": row.flow.graph or {}, "interface": row.interface or {}, "label": row.label, "description": row.description},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("vision", "0040_composite_tools"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="compositetool",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.CreateModel(
            name="CompositeToolVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()),
                ("graph", models.JSONField(default=dict)),
                ("interface", models.JSONField(blank=True, default=dict)),
                ("label", models.CharField(default="", max_length=120)),
                ("description", models.TextField(blank=True, default="")),
                ("saved_at", models.DateTimeField(auto_now_add=True)),
                ("saved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tool", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="vision.compositetool")),
            ],
            options={"unique_together": {("tool", "version")}},
        ),
        migrations.RunPython(seed_snapshots, migrations.RunPython.noop),
    ]
