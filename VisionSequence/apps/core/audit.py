"""Writing the audit trail.

One call per meaningful action, made by the endpoint that performs it:

    audit.record(request, "flow.update", flow, before=old_graph, after=flow.graph)

Rules that keep the trail useful rather than merely large:

- **Changes only, never executions.** Runs already have `FlowRun`, the hourly rollup and the image
  archive; copying them here would flush the real edits out of view.
- **Parameter-level diffs.** Two whole graphs per save tell nobody anything (see `graphdiff`).
- **Failing to audit never fails the request.** A broken trail is bad; a line that stops because the
  trail is broken is worse.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.core.models import AuditLog

log = logging.getLogger(__name__)

#: Longest string kept inside `detail`.
MAX_CHARS = 600
#: How many entries a single detail list keeps.
MAX_ITEMS = 40


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


def _clip(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_CHARS else value[:MAX_CHARS] + "…"
    if isinstance(value, dict):
        return {str(k)[:60]: _clip(v) for k, v in list(value.items())[:MAX_ITEMS]}
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in list(value)[:MAX_ITEMS]]
    text = repr(value)
    return text if len(text) <= 200 else text[:200] + "…"


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    ip = forwarded or request.META.get("REMOTE_ADDR") or ""
    return ip or None


def fields_diff(before: dict[str, Any] | None, after: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any]:
    """Simple before/after for plain records (sources, connections, users…)."""
    before, after = before or {}, after or {}
    out: dict[str, Any] = {}
    for key in keys:
        if before.get(key) != after.get(key):
            out[key] = {"before": _clip(before.get(key)), "after": _clip(after.get(key))}
    return out


def summarize_fields(changes: dict[str, Any], limit: int = 4) -> str:
    bits = [f"{k}: {v['before']} → {v['after']}" for k, v in list(changes.items())[:limit]]
    if len(changes) > limit:
        bits.append(f"+{len(changes) - limit} more")
    return ", ".join(bits)


def record(request, action: str, target=None, *, summary: str = "", detail: Any = None,
           target_type: str = "", target_id: str = "", target_name: str = "") -> AuditLog | None:
    """Write one row. Never raises."""
    try:
        principal = getattr(request, "auth", None) if request is not None else None
        user = getattr(principal, "user", None)
        if target is not None:
            target_type = target_type or type(target).__name__.lower()
            target_id = target_id or str(getattr(target, "pk", "") or "")
            target_name = target_name or str(getattr(target, "name", "") or getattr(target, "username", "") or "")
        return AuditLog.objects.create(
            actor_kind=getattr(principal, "kind", "system"),
            actor=user if getattr(user, "pk", None) else None,
            actor_name=(getattr(principal, "name", "") or "system")[:150],
            action=action[:40],
            target_type=target_type[:24],
            target_id=target_id[:64],
            target_name=target_name[:160],
            summary=summary[:400],
            detail=_clip(detail) if detail is not None else {},
            ip=_client_ip(request),
        )
    except Exception:  # noqa: BLE001 — 稽核失敗不能讓產線停下來
        log.warning("寫入稽核紀錄失敗：%s", action, exc_info=True)
        return None


def out(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "at": row.at.isoformat(),
        "actor": row.actor_name,
        "actor_kind": row.actor_kind,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_name": row.target_name,
        "summary": row.summary,
        "detail": row.detail or {},
        "ip": row.ip or "",
    }


def purge(days: int | None = None) -> int:
    """Drop entries older than `VISION_AUDIT_DAYS` (0 = keep forever)."""
    days = int(_cfg("AUDIT_DAYS", 730) if days is None else days)
    if days <= 0:
        return 0
    cutoff = timezone.now() - timezone.timedelta(days=days)
    return AuditLog.objects.filter(at__lt=cutoff).delete()[0]
