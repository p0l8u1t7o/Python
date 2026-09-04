"""整合追蹤：把整合介面的「命令與結果」記在行程內的環形緩衝，整合頁可即時查看（除錯用）。

每個整合頁一個頻道：`http`（API 觸發執行）、`tcp`（TCP 一行指令）、`modbus`（主動輸出的連線讀寫、
本平台當從站時主站的請求）、`capture`（擷取端）。只留最近 N 筆，不落地、不進資料庫——
熱路徑（執行緒池內）也會呼叫，所以只做 append 與一次 lock，不做格式化以外的工作。
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

#: 整合頁對應的頻道
CHANNELS = ("http", "tcp", "modbus", "capture")
#: 每個頻道保留的筆數
KEEP = 300
MAX_DETAIL_CHARS = 2000

_lock = threading.Lock()
_seq = itertools.count(1)
_buffers: dict[str, list[dict[str, Any]]] = {c: [] for c in CHANNELS}
#: 有沒有人在看（整合頁開著才記，避免產線長跑白做工）；`entries()` 會自動續期。
_watch_until = 0.0
WATCH_S = 120.0


def watching() -> bool:
    return time.monotonic() < _watch_until


def watch(seconds: float = WATCH_S) -> None:
    """整合頁查詢時呼叫：接下來這段時間要記錄。"""
    global _watch_until
    _watch_until = time.monotonic() + max(1.0, float(seconds))


def _clip(value: Any) -> Any:
    """detail 只留得住印得出來的東西，並限制長度（避免影像／大陣列進來）。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_DETAIL_CHARS else value[:MAX_DETAIL_CHARS] + "…"
    if isinstance(value, dict):
        return {str(k)[:80]: _clip(v) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in list(value)[:40]]
    text = repr(value)
    return text if len(text) <= 200 else text[:200] + "…"


def record(channel: str, summary: str, *, direction: str = "in", name: str = "", detail: Any = None, ok: bool = True, ms: float | None = None, force: bool = False) -> int:
    """記一筆命令／結果。`force=True` 時即使沒人在看也記（錯誤值得留著）。回流水號（0＝沒記）。"""
    if channel not in _buffers:
        return 0
    if not (watching() or force or not ok):  # 沒人在看時只留錯誤
        return 0
    entry = {
        "seq": next(_seq), "ts": time.time(), "channel": channel, "direction": direction,
        "name": str(name or "")[:80], "summary": str(summary or "")[:300], "ok": bool(ok),
        "ms": None if ms is None else round(float(ms), 2), "detail": _clip(detail),
    }
    with _lock:
        buf = _buffers[channel]
        buf.append(entry)
        if len(buf) > KEEP:
            del buf[: len(buf) - KEEP]
    return int(entry["seq"])


def entries(channel: str | None = None, *, since: int = 0, limit: int = 200, keep_watching: bool = True) -> list[dict[str, Any]]:
    """取最近的紀錄（seq > since），依 seq 排序。查詢本身會續期「有人在看」。"""
    if keep_watching:
        watch()
    with _lock:
        pools = [_buffers[channel]] if channel in _buffers else list(_buffers.values())
        out = [e for buf in pools for e in buf if e["seq"] > int(since or 0)]
    out.sort(key=lambda e: e["seq"])
    return out[-max(1, min(int(limit or 200), KEEP)) :]


def clear(channel: str | None = None) -> None:
    with _lock:
        for key in ([channel] if channel in _buffers else list(_buffers)):
            _buffers[key].clear()


def stats() -> dict[str, Any]:
    with _lock:
        counts = {k: len(v) for k, v in _buffers.items()}
    return {"channels": counts, "keep": KEEP, "watching": watching()}
