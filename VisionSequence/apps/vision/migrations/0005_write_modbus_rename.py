# 工具改名：write_plc → write_modbus（拿掉 PLC 稱呼，一律 Modbus TCP）。
# 把 DB 裡既有流程與範本的節點 type 換新；graph.LEGACY_TOOL_TYPES 另外兜住舊匯出檔。

from django.db import migrations


def _rewrite(graph: dict) -> bool:
    changed = False
    for node in (graph or {}).get("nodes", []):
        if isinstance(node, dict) and node.get("type") == "write_plc":
            node["type"] = "write_modbus"
            changed = True
    return changed


def forwards(apps, schema_editor):
    for model_name in ("Flow", "FlowTemplate"):
        model = apps.get_model("vision", model_name)
        for row in model.objects.all().iterator():
            if _rewrite(row.graph):
                row.save(update_fields=["graph"])


def backwards(apps, schema_editor):
    for model_name in ("Flow", "FlowTemplate"):
        model = apps.get_model("vision", model_name)
        for row in model.objects.all().iterator():
            changed = False
            for node in (row.graph or {}).get("nodes", []):
                if isinstance(node, dict) and node.get("type") == "write_modbus":
                    node["type"] = "write_plc"
                    changed = True
            if changed:
                row.save(update_fields=["graph"])


class Migration(migrations.Migration):
    dependencies = [("vision", "0004_plan_v02_base")]
    operations = [migrations.RunPython(forwards, backwards)]
