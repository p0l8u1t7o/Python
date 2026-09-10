"""NG image archive: keep the pictures that matter after the run is over.

The in-process `images.ImageStore` only keeps the last `KEEP_RUN_IMAGES` runs per flow and dies
with the process, so "show me what that reject actually looked like" had no answer. This module
writes the pictures of selected runs to disk and records their paths on the `FlowRun` row, which
makes `GET /vision/images/{ref}` able to fall back to the archive — the front end needs no change.

Design notes:

- **Off by default.** Disk sizing is the customer's, not ours: `VISION_ARCHIVE_DEFAULT` is the
  shipping default and each flow overrides it in `Flow.archive_policy`. The flow page nags when a
  flow has produced rejects while archiving is off.
- **Never on the hot path.** Encoding and file writes happen on the persister thread
  (`runner._Persister`), the same one that already batches `FlowRun` inserts. The engine thread only
  grabs references to the arrays it already has.
- **Backpressure over correctness of the archive.** If the persister queue is backing up we skip
  archiving rather than let the queue grow: a slow disk must never stall inspection.
- **Two pictures per run by default** — the source frame and the result frame. `images="all"` keeps
  every node output and is meant for short debugging sessions, not for production.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from django.conf import settings

log = logging.getLogger(__name__)

#: Archive policy modes: never / rejects and failures only / every run.
MODES = ("off", "ng", "all")
#: Which pictures of a run to keep.
PICTURES = ("result", "all")
#: Skip archiving while the persister queue is deeper than this — inspection comes first.
QUEUE_LIMIT = 200

_lock = threading.Lock()
_dropped = 0
_written = 0


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


def root() -> Path:
    """封存根目錄；預設在資產目錄旁邊，可用 VISION_ARCHIVE_DIR 移到大容量磁碟。"""
    custom = str(_cfg("ARCHIVE_DIR", "") or "")
    return Path(custom) if custom else Path(settings.VISION["ASSET_DIR"]).parent / "archive"


def default_policy() -> dict[str, Any]:
    """The shipping default, so an integrator can preset archiving for a whole site in .env."""
    mode = str(_cfg("ARCHIVE_DEFAULT", "off")).lower()
    return {
        "mode": mode if mode in MODES else "off",
        "pictures": "result",
        "sample": 0,      # with mode="ng": also keep 1 in N passing runs (0 = none)
        "format": "jpeg",
        "quality": 85,
    }


def policy_for(flow) -> dict[str, Any]:
    """A flow's effective policy: its own settings over the site default."""
    return sanitize(getattr(flow, "archive_policy", None))


def sanitize(stored: Any) -> dict[str, Any]:
    """Merge a stored policy over the site default; unknown or out-of-range keys are ignored."""
    policy = default_policy()
    stored = stored or {}
    if isinstance(stored, dict):
        if str(stored.get("mode", "")).lower() in MODES:
            policy["mode"] = str(stored["mode"]).lower()
        if str(stored.get("pictures", "")).lower() in PICTURES:
            policy["pictures"] = str(stored["pictures"]).lower()
        for key, cast, lo, hi in (("sample", int, 0, 100000), ("quality", int, 30, 100)):
            try:
                policy[key] = max(lo, min(hi, cast(stored.get(key, policy[key]))))
            except (TypeError, ValueError):
                pass
        if str(stored.get("format", "")).lower() in ("jpeg", "png"):
            policy["format"] = str(stored["format"]).lower()
    return policy


def wanted(policy: dict[str, Any], status: str, run_index: int = 0) -> bool:
    """Should this run be archived? `run_index` drives the pass-run sampling."""
    mode = policy.get("mode", "off")
    if mode == "off":
        return False
    if mode == "all":
        return True
    if status in ("ng", "failed"):
        return True
    sample = int(policy.get("sample") or 0)
    return bool(sample and run_index % sample == 0)


# ---------------------------------------------------------------------------
# Picking the pictures
# ---------------------------------------------------------------------------
def pick_refs(report, policy: dict[str, Any]) -> list[str]:
    """Image refs worth keeping. Prefer result images, otherwise keep the acquisition frame."""
    refs: list[str] = []
    for node_id, node in report.nodes.items():
        for port, value in (node.outputs or {}).items():
            if port == "_image" or not isinstance(value, dict):
                continue
            ref = value.get("ref")
            if isinstance(ref, str) and ref.startswith(f"{report.id}:"):
                refs.append(ref)
        _ = node_id
    if policy.get("pictures") == "all" or len(refs) <= 2:
        return refs
    draw = [ref for ref in refs if ":draw:" in ref or ":draw_result:" in ref]
    source = [ref for ref in refs if any(f":{node}:" in ref for node in ("src", "source", "stereo_grab"))]
    picked = [*(source[:1] or refs[:1]), *(draw[:1] or [])]
    if len(picked) == 1 and not draw:
        return picked
    return list(dict.fromkeys(picked))


def capture(report, store, *, queue_depth: int = 0) -> dict[str, np.ndarray]:
    """Grab the arrays to archive, on the caller's thread. Returns {ref: array} (no copies)."""
    global _dropped
    if queue_depth > QUEUE_LIMIT:
        with _lock:
            _dropped += 1
        return {}
    out: dict[str, np.ndarray] = {}
    for ref in pick_refs(report, report.archive_policy):
        img = store.get(ref)
        if img is not None:
            out[ref] = img
    return out


# ---------------------------------------------------------------------------
# Writing and reading
# ---------------------------------------------------------------------------
def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:80]


def save(report, images: dict[str, np.ndarray]) -> dict[str, str]:
    """Write the pictures; returns {ref: path relative to the archive root}."""
    global _written
    if not images:
        return {}
    from apps.vision.images import encode_image

    policy = getattr(report, "archive_policy", None) or default_policy()
    fmt = policy.get("format", "jpeg")
    quality = int(policy.get("quality", 85))
    day = time.strftime("%Y%m%d", time.localtime(report.started_at or time.time()))
    rel_dir = Path(str(report.flow_id)) / day
    abs_dir = root() / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for ref, img in images.items():
        _, node, port = (ref.split(":", 2) + ["", ""])[:3]
        rel = rel_dir / f"{report.id}-{_safe(node)}-{_safe(port)}.{'png' if fmt == 'png' else 'jpg'}"
        try:
            (root() / rel).write_bytes(encode_image(img, fmt=fmt, quality=quality))
            written[ref] = rel.as_posix()
        except OSError:
            log.warning("寫入封存影像失敗：%s", rel, exc_info=True)
    with _lock:
        _written += len(written)
    return written


def read(run_id: str, ref: str) -> np.ndarray | None:
    """Read one archived picture back (used when the memory cache no longer has it)."""
    from apps.vision.models import FlowRun

    try:
        import uuid as _uuid

        row = FlowRun.objects.filter(pk=_uuid.UUID(run_id)).only("images").first()
    except (ValueError, AttributeError):
        return None
    rel = (row.images or {}).get(ref) if row else None
    if not rel:
        return None
    path = root() / rel
    if not path.exists():
        return None
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)  # Windows 中文路徑
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    return img if img is not None else None


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
def _files() -> list[tuple[float, int, Path]]:
    out: list[tuple[float, int, Path]] = []
    base = root()
    if not base.exists():
        return out
    for path in base.rglob("*"):
        if path.is_file():
            try:
                st = path.stat()
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, path))
    return out


def stats() -> dict[str, Any]:
    files = _files()
    return {"files": len(files), "bytes": sum(f[1] for f in files), "written": _written, "dropped": _dropped, "dir": str(root())}


def purge(*, days: int | None = None, max_bytes: int | None = None) -> dict[str, int]:
    """Delete by age first, then by total size (oldest first). Returns what was removed."""
    days = int(_cfg("ARCHIVE_DAYS", 90) if days is None else days)
    max_bytes = int((float(_cfg("ARCHIVE_MAX_GB", 20)) * (1 << 30)) if max_bytes is None else max_bytes)
    files = sorted(_files())
    removed = freed = 0
    cutoff = time.time() - days * 86400 if days > 0 else 0.0
    keep: list[tuple[float, int, Path]] = []
    for mtime, size, path in files:
        if cutoff and mtime < cutoff:
            try:
                path.unlink()
                removed += 1
                freed += size
                continue
            except OSError:
                pass
        keep.append((mtime, size, path))
    total = sum(f[1] for f in keep)
    for mtime, size, path in keep:
        if max_bytes <= 0 or total <= max_bytes:
            break
        try:
            path.unlink()
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass
        _ = mtime
    _prune_empty_dirs()
    return {"removed": removed, "freed": freed}


def _prune_empty_dirs() -> None:
    base = root()
    if not base.exists():
        return
    for path in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


def drop_run(run_id: str, images: dict[str, str] | None) -> None:
    """Remove one run's archived pictures (called when its FlowRun row is pruned)."""
    for rel in (images or {}).values():
        try:
            (root() / rel).unlink(missing_ok=True)
        except OSError:
            pass


def clear() -> None:
    """Testing helper: wipe the archive directory."""
    global _written, _dropped
    shutil.rmtree(root(), ignore_errors=True)
    with _lock:
        _written = _dropped = 0
