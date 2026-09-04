"""Flow version history: snapshot every save, compare, restore, mark a version as released.

`Flow.version` used to be a bare counter, so "baseline: flow v40" pointed at a graph nobody could
open any more. Every save now stores its graph here; restoring writes a **new** version rather than
rewriting history, which is what makes the trail usable as evidence.

Retention keeps the most recent `KEEP_VERSIONS` plus every released version — an engineer's signed
-off version is never thrown away by a housekeeping job.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.vision.graphdiff import diff, summarize
from apps.vision.models import Flow, FlowVersion

log = logging.getLogger(__name__)


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


def snapshot(flow: Flow, *, user=None, note: str = "") -> FlowVersion | None:
    """Record the flow's current graph as `flow.version`. Idempotent per version."""
    if not flow.pk:
        return None
    row, created = FlowVersion.objects.get_or_create(
        flow=flow, version=flow.version,
        defaults={"graph": flow.graph or {}, "saved_by": user if getattr(user, "pk", None) else None, "note": note[:200]},
    )
    if created:
        prune(flow)
    return row


def prune(flow: Flow) -> int:
    """Drop old snapshots beyond the keep count; released versions are never dropped."""
    keep = max(1, int(_cfg("KEEP_VERSIONS", 50)))
    ids = list(
        FlowVersion.objects.filter(flow=flow, is_released=False).order_by("-version").values_list("id", flat=True)[keep:]
    )
    if not ids:
        return 0
    return FlowVersion.objects.filter(id__in=ids).delete()[0]


def out(row: FlowVersion, *, graph: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": row.version,
        "saved_at": row.saved_at.isoformat(),
        "saved_by": row.saved_by.username if row.saved_by_id else "",
        "note": row.note,
        "is_released": row.is_released,
        "node_count": len((row.graph or {}).get("nodes") or []),
    }
    if graph:
        data["graph"] = row.graph or {}
    return data


def listing(flow: Flow) -> list[dict[str, Any]]:
    """Newest first, each row carrying what changed against the version before it."""
    rows = list(FlowVersion.objects.filter(flow=flow).select_related("saved_by").order_by("-version"))
    items: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        entry = out(row)
        older = rows[i + 1] if i + 1 < len(rows) else None
        if older is not None:
            changes = diff(older.graph, row.graph)
            entry["changes"] = changes["count"]
            entry["summary"] = summarize(changes)
        else:
            entry["changes"] = 0
            entry["summary"] = ""
        entry["is_current"] = row.version == flow.version
        items.append(entry)
    return items


def compare(flow: Flow, version: int) -> dict[str, Any]:
    """That version against the flow as it stands now."""
    row = FlowVersion.objects.filter(flow=flow, version=version).select_related("saved_by").first()
    if row is None:
        return {}
    changes = diff(row.graph, flow.graph or {})
    return {**out(row, graph=True), "diff": changes, "summary": summarize(changes), "current_version": flow.version}


def restore(flow: Flow, version: int, *, user=None) -> FlowVersion | None:
    """Bring an old graph back as a new version. History is never rewritten."""
    row = FlowVersion.objects.filter(flow=flow, version=version).first()
    if row is None:
        return None
    snapshot(flow, user=user)  # 保住目前這一版，否則還原前的狀態會消失
    flow.graph = row.graph or {}
    flow.version += 1
    flow.save(update_fields=["graph", "version", "updated_at"])
    return snapshot(flow, user=user, note=f"restored from v{version}")
