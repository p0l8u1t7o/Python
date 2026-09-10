"""站台行程內佇列；鎖內完成配對與移除，熱路徑不存取資料庫。"""

from __future__ import annotations

import copy
import json
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from apps.vision import variables


class QueueError(ValueError):
    """佇列設定或內容不合法。"""


def check_name(name: Any) -> str:
    text = str(name or "")
    if not variables.NAME_RE.fullmatch(text):
        raise QueueError("Queue names must use 1-64 letters, digits or underscores and cannot start with a digit")
    return text


def normalize(values: Any) -> dict:
    """先拒絕巢狀影像，再沿用流程變數正規化及容量限制。"""
    def check(value):
        if isinstance(value, np.ndarray):
            raise QueueError("Queue values cannot contain images; connect the image port instead")
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str):
                    raise QueueError("Queue value names must be strings")
                check(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                check(v)

    if not isinstance(values, dict):
        raise QueueError("Queue data must be a dictionary")
    try:
        check(values)
        result, _ = variables.normalize(values)
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (variables.VariableError, ValueError, TypeError, RecursionError) as exc:
        raise QueueError(str(exc)) from None
    if len(text.encode("utf-8")) > variables.MAX_JSON_BYTES:
        raise QueueError("Queue values exceed the 64 KB limit")
    return result


@dataclass
class _Queue:
    items: list[dict] = field(default_factory=list)
    seq: int = 0
    dropped: int = 0


class QueueStore:
    def __init__(self):
        self.condition = threading.Condition()
        self._queues: dict[str, _Queue] = {}

    def fork(self):
        """試執行取一致副本；不清除正式佇列的過期項目。"""
        other = QueueStore()
        with self.condition:
            other._queues = copy.deepcopy(self._queues)
        return other

    @staticmethod
    def _expire(q, now):
        alive = [item for item in q.items if not item["_expires"] or item["_expires"] > now]
        q.dropped += len(q.items) - len(alive)
        q.items = alive

    @staticmethod
    def _status(name, q, now):
        return {"name": name, "size": len(q.items), "dropped": q.dropped,
                "oldest_age_ms": max(0.0, (now - q.items[0]["_born"]) * 1000) if q.items else 0.0}

    def push(self, name, values, *, key="", max_items=64, on_full="drop_oldest", ttl_s=0,
             image_ref=None, flow_id=0, run_id=""):
        name = check_name(name)
        values = normalize(values)
        if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 1024:
            raise QueueError("Queue capacity must be between 1 and 1024")
        if on_full not in ("drop_oldest", "reject"):
            raise QueueError("Unknown full queue policy")
        if not isinstance(ttl_s, (float, int)) or not math.isfinite(ttl_s) or ttl_s < 0:
            raise QueueError("Queue lifetime must be a finite non-negative number")
        if not isinstance(key, str) or len(key.encode("utf-8")) > 65536:
            raise QueueError("Queue keys must be text of at most 64 KB")
        if image_ref is not None and not isinstance(image_ref, str):
            raise QueueError("Image references must be text")
        with self.condition:
            now = time.monotonic()
            q = self._queues.setdefault(name, _Queue())
            self._expire(q, now)
            dropped = 0
            if len(q.items) >= max_items:
                if on_full == "reject":
                    return {"seq": 0, "size": len(q.items), "dropped": 0, "accepted": False}
                dropped = len(q.items) - max_items + 1
                del q.items[:dropped]
                q.dropped += dropped
            q.seq += 1
            q.items.append({"seq": q.seq, "at": time.time(), "key": key, "values": values,
                            "image_ref": image_ref, "flow_id": flow_id, "run_id": run_id,
                            "_born": now, "_expires": now + ttl_s if ttl_s else 0})
            self.condition.notify_all()
            return {"seq": q.seq, "size": len(q.items), "dropped": dropped, "accepted": True}

    def pop(self, name, *, match="fifo", key="", remove=True, wait_ms=0):
        name = check_name(name)
        if match not in ("fifo", "lifo", "key"):
            raise QueueError("Unknown queue match mode")
        if not isinstance(wait_ms, (float, int)) or not math.isfinite(wait_ms) or not 0 <= wait_ms <= 2000:
            raise QueueError("Queue wait must be between 0 and 2000 ms")
        deadline = time.monotonic() + wait_ms / 1000
        with self.condition:
            while True:
                now = time.monotonic()
                q = self._queues.get(name)
                if q is not None:
                    self._expire(q, now)
                    index = next((i for i, item in enumerate(q.items) if item["key"] == key), None) if match == "key" else (len(q.items) - 1 if match == "lifo" else 0)
                    if q.items and index is not None:
                        item = copy.deepcopy(q.items.pop(index) if remove else q.items[index])
                        item["age_ms"] = max(0.0, (now - item.pop("_born")) * 1000)
                        item.pop("_expires")
                        return item, self._status(name, q, now)
                remaining = deadline - now
                if remaining <= 0:
                    return None, self._status(name, q or _Queue(), now)
                self.condition.wait(remaining)

    def snapshot(self):
        with self.condition:
            now = time.monotonic()
            for q in self._queues.values():
                self._expire(q, now)
            return [self._status(name, q, now) for name, q in sorted(self._queues.items())]

    def clear(self, name):
        name = check_name(name)
        with self.condition:
            q = self._queues.get(name)
            count = len(q.items) if q else 0
            if q:
                q.items.clear()
            self.condition.notify_all()
            return count


store = QueueStore()


def for_context(ctx):
    """覆蓋層只放本次引擎共用的私有 context，不回傳到產品資料。"""
    if not ctx.sandboxed():
        return store
    if "_queues_overlay" not in ctx.context:
        ctx.context["_queues_overlay"] = store.fork()
    return ctx.context["_queues_overlay"]
