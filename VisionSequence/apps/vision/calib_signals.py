"""手眼標定精靈的短期通訊訊號佇列。

訊號只服務幾分鐘內的標定流程，重啟後重來；因此不進資料庫。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

KINDS = ("start", "point", "end", "teach")
MAX_ITEMS = 64

_lock = threading.Lock()
_seq = 0
_items: deque[dict[str, Any]] = deque(maxlen=MAX_ITEMS)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def push(kind: str, x: Any = None, y: Any = None, r: Any = None, source: str = "") -> dict[str, Any]:
    """新增一筆標定訊號，回佇列中的標準形狀。"""
    global _seq
    if kind not in KINDS:
        raise ValueError(f"Unknown calibration signal '{kind}'")
    item = {
        "seq": 0,
        "kind": kind,
        "x": _number(x),
        "y": _number(y),
        "r": _number(r),
        "ts": time.time(),
        "source": str(source or "")[:200],
    }
    with _lock:
        _seq += 1
        item["seq"] = _seq
        _items.append(item)
        return dict(item)


def since(seq: int) -> list[dict[str, Any]]:
    """回傳序號大於 `seq` 的訊號。"""
    with _lock:
        return [dict(item) for item in _items if int(item.get("seq", 0)) > int(seq)]


def latest() -> dict[str, Any] | None:
    """回最新一筆訊號。"""
    with _lock:
        return dict(_items[-1]) if _items else None


def clear() -> None:
    """清空佇列但保留單調遞增序號，避免輪詢端錯過清空後的新訊號。"""
    with _lock:
        _items.clear()


def current_seq() -> int:
    """目前最後序號；給空回應的 last_seq 使用。"""
    with _lock:
        return _seq

