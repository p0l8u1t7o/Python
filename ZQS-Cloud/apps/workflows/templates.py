"""流程範本：內建目錄、佔位符化、依場域解回。

「點一下範本就載進畫布直接用」要成立，範本裡不能寫死設備 id——示範場域的
電池 id 在客戶的場域不存在。所以範本存的是 ``{BESS}`` 這類**角色佔位符**，
載入時依目標場域的能源資產解成真正的設備 id；解不回來的留著並回報，
讓使用者在畫布上自己挑，不是默默塞一個錯的設備。

內建範本直接沿用 :mod:`apps.core.showcase_workflows` 的建構器——那六個流程
本來就是用佔位符寫的，示範租戶與範本目錄讀同一份，不會各自漂移。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from apps.ems.models import AssetRole, EnergyAsset

#: 佔位符 → 在目標場域怎麼找設備。資產角色優先；EMS 控制器沒有資產，用類別。
PLACEHOLDER_ROLES: dict[str, str] = {
    "BESS": AssetRole.BATTERY,
    "METER": AssetRole.GRID_METER,
    "PV": AssetRole.PV,
    "LOAD": AssetRole.LOAD_METER,
}
PLACEHOLDER_CATEGORY: dict[str, str] = {"EMS": "controller"}
PLACEHOLDER_LABELS: dict[str, str] = {
    "BESS": "電池（BESS）", "METER": "市電關口電表", "PV": "光電", "LOAD": "負載電表", "EMS": "EMS 控制器",
}
_PLACEHOLDER = re.compile(r"\{(BESS|METER|PV|LOAD|EMS|WORKFLOW:[^}]+)\}")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(slots=True)
class Template:
    id: str
    name: str
    description: str
    source: str  # builtin | custom
    graph: dict
    placeholders: list[str] = field(default_factory=list)
    category: str = ""

    @property
    def node_count(self) -> int:
        return len([n for n in self.graph.get("nodes", []) if n.get("type") != "note"])


def placeholders_in(graph: dict) -> list[str]:
    found = sorted({m.group(1) for m in _PLACEHOLDER.finditer(json.dumps(graph, ensure_ascii=False))})
    return found


# --------------------------------------------------------------------------
# Built-in catalogue
# --------------------------------------------------------------------------
BUILTIN_CATEGORIES = {
    "削峰與低電量保護": "demand", "離峰充電排程": "tariff", "光電餘電優先充電": "pv",
    "電池溫度連鎖": "safety", "需量反應演練": "demand", "主控排程": "orchestration",
}


def builtin_templates() -> list[Template]:
    from apps.core.showcase_workflows import SHOWCASE_WORKFLOWS

    out = []
    for index, (name, description, _site_code, build) in enumerate(SHOWCASE_WORKFLOWS):
        graph = build()
        out.append(Template(
            id=f"builtin:{index}", name=name, description=description, source="builtin",
            graph=graph, placeholders=placeholders_in(graph), category=BUILTIN_CATEGORIES.get(name, ""),
        ))
    return out


def builtin_by_id(template_id: str) -> Template | None:
    return next((t for t in builtin_templates() if t.id == template_id), None)


# --------------------------------------------------------------------------
# Templatize (save) / instantiate (load)
# --------------------------------------------------------------------------
def _role_of_device(organization) -> dict[str, str]:
    """device id → placeholder key，依該租戶所有啟用資產與 EMS 控制器。"""
    from apps.devices.models import Device

    mapping: dict[str, str] = {}
    role_to_key = {role: key for key, role in PLACEHOLDER_ROLES.items()}
    for asset in EnergyAsset.objects.filter(organization=organization, is_active=True).select_related("device"):
        key = role_to_key.get(asset.role)
        if key and asset.device_id:
            mapping[str(asset.device_id)] = key
    for device in Device.objects.filter(
        organization=organization, deleted_at__isnull=True, device_type__category="controller"
    ):
        mapping.setdefault(str(device.id), "EMS")
    return mapping


def templatize(graph: dict, organization) -> tuple[dict, list[str]]:
    """把圖裡的設備 id 與子流程 id 換成佔位符。回傳 (graph, placeholders)。"""
    from apps.workflows.models import Workflow

    devices = _role_of_device(organization)
    workflows = {
        str(pk): name
        for pk, name in Workflow.objects.filter(organization=organization, deleted_at__isnull=True).values_list("id", "name")
    }

    def swap(value):
        if isinstance(value, str):
            if value in devices:
                return "{" + devices[value] + "}"
            if value in workflows:
                return "{WORKFLOW:" + workflows[value] + "}"
            return value
        if isinstance(value, dict):
            return {k: swap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [swap(v) for v in value]
        return value

    nodes = []
    for node in graph.get("nodes", []):
        clean = dict(node)
        clean["params"] = swap(node.get("params") or {})
        nodes.append(clean)
    out = {"nodes": nodes, "edges": list(graph.get("edges", []))}
    return out, placeholders_in(out)


def resolve_for_site(site, organization) -> dict[str, str]:
    """目標場域的佔位符解法：角色資產 → 設備 id；EMS 控制器 → 類別。"""
    from apps.devices.models import Device

    values: dict[str, str] = {}
    assets = EnergyAsset.objects.filter(site=site, is_active=True).order_by("created_at")
    for key, role in PLACEHOLDER_ROLES.items():
        asset = next((a for a in assets if a.role == role), None)
        if asset is not None:
            values[key] = str(asset.device_id)
    for key, category in PLACEHOLDER_CATEGORY.items():
        device = Device.objects.filter(
            organization=organization, site=site, deleted_at__isnull=True, device_type__category=category
        ).order_by("device_id").first()
        if device is not None:
            values[key] = str(device.id)
    return values


def instantiate(template_graph: dict, site, organization) -> tuple[dict, list[str]]:
    """解回佔位符。回傳 (graph, missing)；missing 是解不回來、原樣留在圖裡的鍵。"""
    from apps.workflows.models import Workflow

    values = resolve_for_site(site, organization) if site is not None else {}
    workflows = {
        name: str(pk)
        for pk, name in Workflow.objects.filter(organization=organization, deleted_at__isnull=True).values_list("id", "name")
    }
    missing: set[str] = set()

    def fill(match: re.Match) -> str:
        key = match.group(1)
        if key.startswith("WORKFLOW:"):
            target = workflows.get(key[len("WORKFLOW:"):])
            if target:
                return target
        elif key in values:
            return values[key]
        missing.add(key)
        return match.group(0)

    text = json.dumps(template_graph, ensure_ascii=False)
    text = _PLACEHOLDER.sub(fill, text)
    graph = json.loads(text)
    # 載入成新流程時節點 id 要獨一無二，避免和畫布上既有節點撞名。
    return graph, sorted(missing)


def with_fresh_ids(graph: dict) -> dict:
    """給每個節點新的 id（邊一起改），載進已有內容的畫布時不會撞 id。"""
    mapping = {node["id"]: f"{node['id'].rsplit('-', 1)[0]}-{uuid.uuid4().hex[:6]}" for node in graph.get("nodes", [])}
    nodes = [{**node, "id": mapping[node["id"]]} for node in graph.get("nodes", [])]
    edges = []
    for edge in graph.get("edges", []):
        source = mapping.get(edge["source"], edge["source"])
        target = mapping.get(edge["target"], edge["target"])
        edges.append({**edge, "id": f"e-{source}-{edge.get('source_handle', '')}-{target}", "source": source, "target": target})
    return {"nodes": nodes, "edges": edges}
