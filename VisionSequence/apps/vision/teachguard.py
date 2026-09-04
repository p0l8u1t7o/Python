"""操作員的參數邊界：新舊圖之間只准 `teach=True` 參數的值不同。

現場人員每天要微調門檻，但不該碰流程結構。工具已經用 `Param.teach` 標好了哪些是現場可調的
（目前 58 個），這裡就照那個標記把關——不必另外發明一套「現場參數」清單。
"""

from __future__ import annotations

from typing import Any

from apps.vision.tools import base as tools_base


class StructureChanged(ValueError):
    """改到了結構或非現場參數；訊息直接給使用者看。"""


def _teach_keys(node_type: str) -> set[str]:
    try:
        tool = tools_base.get(node_type)
    except Exception:  # noqa: BLE001 — 未知工具一律當成不可改
        return set()
    return {p.key for p in getattr(tool, "params", []) if getattr(p, "teach", False)}


def assert_teach_only(old: dict[str, Any], new: dict[str, Any]) -> None:
    """`new` 相對 `old` 只有現場可調參數的值變了；否則拋 StructureChanged。"""
    old_nodes = {n.get("id"): n for n in (old or {}).get("nodes") or []}
    new_nodes = {n.get("id"): n for n in (new or {}).get("nodes") or []}
    if set(old_nodes) != set(new_nodes):
        raise StructureChanged("Operators cannot add or remove steps")
    if (old or {}).get("edges") != (new or {}).get("edges"):
        raise StructureChanged("Operators cannot change how steps are connected")
    for node_id, old_node in old_nodes.items():
        new_node = new_nodes[node_id]
        if old_node.get("type") != new_node.get("type"):
            raise StructureChanged(f"Operators cannot change the tool of step '{node_id}'")
        allowed = _teach_keys(str(old_node.get("type") or ""))
        old_params = old_node.get("params") or {}
        new_params = new_node.get("params") or {}
        for key in set(old_params) | set(new_params):
            if old_params.get(key) == new_params.get(key):
                continue
            if key not in allowed:
                raise StructureChanged(f"'{key}' on step '{node_id}' is not a field operators can adjust")
        for key in set(old_node) | set(new_node):  # 位置、備註等其餘欄位
            if key in ("params",):
                continue
            if old_node.get(key) != new_node.get(key) and key not in ("position", "label"):
                raise StructureChanged(f"Operators cannot change '{key}' of step '{node_id}'")
