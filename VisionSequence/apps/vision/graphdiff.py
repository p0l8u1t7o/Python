"""What changed between two flow graphs, in the terms a quality engineer reads.

Storing two whole graphs per save and diffing them as JSON tells nobody anything. What people
actually ask is "who moved the threshold from 60 to 46" — so the unit here is **one parameter on one
step**, with structural edits reported as counts rather than as a wall of JSON.

Used by version compare (`api_versions.py`) and by the audit trail (`audit.py`).
"""

from __future__ import annotations

from typing import Any

#: Node keys that carry no meaning for an inspection result (canvas placement, cosmetics).
COSMETIC = ("position", "width", "height", "selected", "dragging")
#: Longest value rendered in a diff entry; graphs can hold base64-ish strings and whole scripts.
MAX_VALUE_CHARS = 300


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + "…"
    if isinstance(value, (list, tuple)) and len(value) > 20:
        return list(value[:20]) + [f"…(+{len(value) - 20})"]
    return value


def _nodes(graph: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {str(n.get("id")): n for n in (graph or {}).get("nodes") or [] if n.get("id")}


def _edges(graph: dict[str, Any] | None) -> set[tuple[str, str, str, str]]:
    out = set()
    for e in (graph or {}).get("edges") or []:
        out.add((str(e.get("source")), str(e.get("source_handle") or ""), str(e.get("target")), str(e.get("target_handle") or "")))
    return out


def diff(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """A readable change set: parameter edits listed one by one, structure summarised."""
    old_nodes, new_nodes = _nodes(old), _nodes(new)
    added = sorted(set(new_nodes) - set(old_nodes))
    removed = sorted(set(old_nodes) - set(new_nodes))
    retyped: list[dict[str, Any]] = []
    params: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    for node_id in sorted(set(old_nodes) & set(new_nodes)):
        before, after = old_nodes[node_id], new_nodes[node_id]
        if before.get("type") != after.get("type"):
            retyped.append({"node": node_id, "before": before.get("type"), "after": after.get("type")})
        if before.get("label") != after.get("label"):
            renamed.append({"node": node_id, "before": before.get("label"), "after": after.get("label")})
        old_params = before.get("params") or {}
        new_params = after.get("params") or {}
        for key in sorted(set(old_params) | set(new_params)):
            if old_params.get(key) != new_params.get(key):
                params.append({
                    "node": node_id, "type": after.get("type"), "param": key,
                    "before": _short(old_params.get(key)), "after": _short(new_params.get(key)),
                })
    old_edges, new_edges = _edges(old), _edges(new)
    edges_added = len(new_edges - old_edges)
    edges_removed = len(old_edges - new_edges)
    cosmetic_only = 0
    for node_id in set(old_nodes) & set(new_nodes):
        for key in COSMETIC:
            if old_nodes[node_id].get(key) != new_nodes[node_id].get(key):
                cosmetic_only += 1
                break
    return {
        "added": added,
        "removed": removed,
        "retyped": retyped,
        "renamed": renamed,
        "params": params,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
        "moved": cosmetic_only,
        "structural": bool(added or removed or retyped or edges_added or edges_removed),
        "count": len(added) + len(removed) + len(retyped) + len(params) + edges_added + edges_removed,
    }


def summarize(changes: dict[str, Any], limit: int = 3) -> str:
    """One line for a list row: "threshold 60 → 46, +1 step"."""
    bits: list[str] = []
    for entry in changes.get("params", [])[:limit]:
        bits.append(f"{entry['param']} {entry['before']} → {entry['after']}")
    extra = len(changes.get("params", [])) - limit
    if extra > 0:
        bits.append(f"+{extra} more")
    if changes.get("added"):
        bits.append(f"+{len(changes['added'])} step")
    if changes.get("removed"):
        bits.append(f"-{len(changes['removed'])} step")
    if changes.get("edges_added") or changes.get("edges_removed"):
        bits.append(f"{changes.get('edges_added', 0)}/{changes.get('edges_removed', 0)} links")
    if not bits and changes.get("moved"):
        bits.append("layout only")
    return ", ".join(bits)
