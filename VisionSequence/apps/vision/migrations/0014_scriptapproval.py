"""ScriptApproval：Python 腳本工具的核准清單（管理員儲存流程時登記程式碼 sha256，引擎只執行清單內的腳本）。"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("vision", "0013_batchrun_flow"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScriptApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(max_length=64, unique=True)),
                ("code", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_scripts", to=settings.AUTH_USER_MODEL)),
                ("flow", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="script_approvals", to="vision.flow")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
