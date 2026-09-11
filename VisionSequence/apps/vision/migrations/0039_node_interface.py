"""PRODUCT-DIRECTION v2 P0：graph 節點的 params._publish → interface.outputs[].alias、exposed_params → interface.inputs[]（param:<key>）。

沒有客戶資料，所以程式碼不留讀取相容層（validate_graph 會直接拒絕舊欄位）；這支只把開發站台既有的流程／版本／範本／
批次快照／助手工作階段裡的圖轉成新形狀，跑一次即可。
"""
from django.db import migrations

PARAM_PREFIX = "param:"


def _convert_node(node):
    if not isinstance(node, dict):
        return False
    changed = False
    params = node.get("params")
    iface = node.get("interface") if isinstance(node.get("interface"), dict) else {}
    outputs = list(iface.get("outputs") or [])
    inputs = list(iface.get("inputs") or [])
    if isinstance(params, dict) and "_publish" in params:
        publish = params.pop("_publish")
        if isinstance(publish, dict):
            for port, name in publish.items():
                if str(name or "").strip():
                    outputs.append({"key": str(port), "alias": str(name).strip()})
        changed = True
    if "exposed_params" in node:
        exposed = node.pop("exposed_params")
        if isinstance(exposed, list):
            for key in exposed:
                inputs.append({"key": f"{PARAM_PREFIX}{key}", "exposed": True})
        changed = True
    if changed:
        iface = {**iface}
        if outputs:
            iface["outputs"] = outputs
        if inputs:
            iface["inputs"] = inputs
        if iface:
            node["interface"] = iface
        else:
            node.pop("interface", None)
    return changed


def _convert_graph(graph):
    if not isinstance(graph, dict):
        return False
    changed = False
    for node in graph.get("nodes") or []:
        changed = _convert_node(node) or changed
    return changed


def forwards(apps, schema_editor):
    for model_name in ("Flow", "FlowVersion", "FlowTemplate", "AgentSession", "BatchRun"):
        model = apps.get_model("vision", model_name)
        for row in model.objects.all().only("id", "graph"):
            if _convert_graph(row.graph):
                row.save(update_fields=["graph"])


class Migration(migrations.Migration):
    dependencies = [("vision", "0038_inspection_trial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
