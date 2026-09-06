"""深度學習工具與訓練方式改名（產品表面不再出現技術名稱）：既有流程／版本／範本圖的節點 type、教導專案的 trainer_kind、模型資產 meta 的 tool_key 一併改掉。"""

from django.db import migrations

TOOL_MAP = {"yolo_detect": "ai_detect", "yolo_segment": "ai_segment", "yolo_classify": "ai_classify", "yolo_pose": "ai_pose", "yolo_obb": "ai_obb"}
TRAINER_MAP = {"yolo_seg": "ai_seg", "yolo_detect": "ai_detect", "yolo_cls": "ai_cls", "yolo_obb": "ai_obb"}


def _rename_graph(graph):
    changed = False
    for node in (graph or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("type") in TOOL_MAP:
            node["type"] = TOOL_MAP[node["type"]]
            changed = True
    return changed


def forwards(apps, schema_editor):
    for model_name in ("Flow", "FlowVersion", "FlowTemplate"):
        model = apps.get_model("vision", model_name)
        for row in model.objects.all().iterator():
            graph = row.graph
            if isinstance(graph, dict) and _rename_graph(graph):
                row.graph = graph
                row.save(update_fields=["graph"])
    DlProject = apps.get_model("vision", "DlProject")
    for old, new in TRAINER_MAP.items():
        DlProject.objects.filter(trainer_kind=old).update(trainer_kind=new)
    Asset = apps.get_model("vision", "Asset")
    for asset in Asset.objects.filter(kind="model").iterator():
        meta = asset.meta if isinstance(asset.meta, dict) else None
        if not meta:
            continue
        changed = False
        for key in ("tool_key", "weights_tool_key"):
            if meta.get(key) in TOOL_MAP:
                meta[key] = TOOL_MAP[meta[key]]
                changed = True
        if meta.get("trainer_kind") in TRAINER_MAP:
            meta["trainer_kind"] = TRAINER_MAP[meta["trainer_kind"]]
            changed = True
        if changed:
            asset.meta = meta
            asset.save(update_fields=["meta"])


class Migration(migrations.Migration):
    dependencies = [("vision", "0023_measurement_log")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
