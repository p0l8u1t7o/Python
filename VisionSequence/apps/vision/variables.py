"""流程變數：跨執行、跨流程的狀態（累計計數、上一片的結果、PLC 換線送來的料號）。

資料只沿著邊走的 DAG 沒有地方放「上一次」——這裡補上兩個範圍：
  flow    以 flow_id 為鍵，同一條流程的每次 run 都看得到
  station 整站共用（flow_id=None），多條流程協作用

**記憶體為主，熱路徑不碰資料庫**：引擎執行緒只讀寫這裡的 dict；載入在呼叫者執行緒（`ensure_loaded`，
runner.submit 之前），寫回由持久化執行緒（`flush`）批次做。可 JSON 化的值才落地；影像（ndarray）只留在記憶體
（重開機就沒了，但「跟上一片比」這種用途剛好夠）。

試執行（preview）、批次測試與 AI 試跑**不會**碰到這裡：ToolContext 在沙箱裡用每次 run 自己的覆蓋層，
否則工具頁每按一次試執行，產線的計數就多一。
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_JSON_BYTES = 64 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
SCOPES = ("flow", "station")

Scope = int | None  # flow_id；None＝站台


class VariableError(ValueError):
    """名稱或值不合法（訊息給使用者看，一律英文）。"""


def check_name(name: Any) -> str:
    text = str(name or "").strip()
    if not NAME_RE.match(text):
        raise VariableError("A variable name is letters, digits and underscores, starting with a letter (up to 64 characters)")
    return text


def normalize(value: Any) -> tuple[Any, bool]:
    """回 (可存的值, 是否可持久化)。numpy 純量轉成 Python 型別；影像原樣留在記憶體。"""
    if isinstance(value, np.ndarray):
        if value.nbytes > MAX_IMAGE_BYTES:
            raise VariableError("That image is too large to keep as a variable (32 MB limit)")
        return value, False
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        value = None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value, True
    if isinstance(value, (list, tuple, dict)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=_jsonable)
        except (TypeError, ValueError) as exc:
            raise VariableError(f"That value cannot be stored: {exc}") from None
        if len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise VariableError("That value is too large to store (64 KB limit)")
        return json.loads(text), True
    raise VariableError(f"Values of type {type(value).__name__} cannot be stored as a variable")


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


class VariableStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values: dict[Scope, dict[str, Any]] = {}
        self._volatile: set[tuple[Scope, str]] = set()
        self._dirty: set[tuple[Scope, str]] = set()
        self._loaded: set[Scope] = set()
        self._flush_lock = threading.Lock()  # write-through 與持久化執行緒不會同時寫同一列
        #: 有東西要寫回時通知（runner 把持久化執行緒的 ensure 掛在這裡；測試可換掉）
        self.on_dirty: Callable[[], None] | None = None

    # -- 讀寫（熱路徑） ---------------------------------------------------------------------------
    def get(self, scope: Scope, name: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(scope, {}).get(name, default)

    def has(self, scope: Scope, name: str) -> bool:
        with self._lock:
            return name in self._values.get(scope, {})

    def set(self, scope: Scope, name: str, value: Any) -> Any:
        """回上一個值（沒有回 None）。"""
        name = check_name(name)
        stored, persistent = normalize(value)
        with self._lock:
            bucket = self._values.setdefault(scope, {})
            previous = bucket.get(name)
            bucket[name] = stored
            key = (scope, name)
            if persistent:
                self._volatile.discard(key)
                self._dirty.add(key)
            else:
                self._volatile.add(key)
                self._dirty.add(key)  # 落地時會把舊的持久值刪掉，避免重開機後讀到過期的數字
        self._notify()
        return previous

    def delete(self, scope: Scope, name: str) -> bool:
        name = check_name(name)
        with self._lock:
            bucket = self._values.get(scope, {})
            if name not in bucket:
                return False
            del bucket[name]
            self._volatile.discard((scope, name))
            self._dirty.add((scope, name))
        self._notify()
        return True

    def snapshot(self, scope: Scope) -> dict[str, Any]:
        """給 API 與畫面：影像用描述代替。"""
        with self._lock:
            out = {}
            for name, value in self._values.get(scope, {}).items():
                if isinstance(value, np.ndarray):
                    # 形狀不一定是 (h, w)：工具可能存 1 維佔位或 0 維純量。
                    # 這裡是顯示／API 路徑（board、dashboard、變數面板都走它），
                    # 讀不到寬高就回 0，**絕不能讓一個奇怪的形狀把整個看板打成 500**。
                    h = int(value.shape[0]) if value.ndim >= 1 else 0
                    w = int(value.shape[1]) if value.ndim >= 2 else 0
                    out[name] = {"image": True, "width": w, "height": h}
                else:
                    out[name] = value
            return out

    def _notify(self) -> None:
        cb = self.on_dirty
        if cb is not None:
            try:
                cb()
            except Exception:  # noqa: BLE001
                log.exception("variables.on_dirty 失敗")

    # -- 載入與寫回（都在非引擎執行緒） ------------------------------------------------------------
    def ensure_loaded(self, scope: Scope) -> None:
        """第一次用到某個範圍時從資料庫載入（呼叫者執行緒；之後不再碰 DB）。"""
        with self._lock:
            if scope in self._loaded:
                return
        from apps.vision.models import FlowVariable

        rows = FlowVariable.objects.filter(flow_id=scope).values_list("name", "value")
        with self._lock:
            if scope in self._loaded:
                return
            bucket = self._values.setdefault(scope, {})
            for name, value in rows:
                bucket.setdefault(name, value)  # 記憶體裡已經有更新的值就不蓋
            self._loaded.add(scope)

    def flush(self) -> int:
        """把髒的鍵寫回資料庫；回寫了幾個。持久化執行緒定時呼叫，API 寫入後也會呼叫。"""
        with self._flush_lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        with self._lock:
            if not self._dirty:
                return 0
            pending = list(self._dirty)
            self._dirty.clear()
            items = []
            for scope, name in pending:
                value = self._values.get(scope, {}).get(name, _MISSING)
                items.append((scope, name, value, (scope, name) in self._volatile))
        from django.db import transaction

        from apps.vision.models import FlowVariable

        written = 0
        try:
            with transaction.atomic():
                for scope, name, value, volatile in items:
                    if value is _MISSING or volatile:
                        FlowVariable.objects.filter(flow_id=scope, name=name).delete()
                    else:
                        FlowVariable.objects.update_or_create(flow_id=scope, name=name, defaults={"value": value})
                    written += 1
        except Exception:  # noqa: BLE001
            log.exception("流程變數寫回失敗，下次再試")
            with self._lock:
                self._dirty.update((s, n) for s, n, _, _ in items)
        return written

    def forget(self, scope: Scope) -> None:
        """流程被刪：記憶體也清掉（DB 由 CASCADE 處理）。"""
        with self._lock:
            self._values.pop(scope, None)
            self._loaded.discard(scope)
            self._volatile = {k for k in self._volatile if k[0] != scope}
            self._dirty = {k for k in self._dirty if k[0] != scope}

    def clear(self) -> None:
        """測試用。"""
        with self._lock:
            self._values.clear()
            self._volatile.clear()
            self._dirty.clear()
            self._loaded.clear()


_MISSING = object()
store = VariableStore()


def scope_for(flow_id: int | None, scope: str) -> Scope:
    if scope not in SCOPES:
        raise VariableError("scope must be flow or station")
    return None if scope == "station" else flow_id


def parse_default(text: Any) -> Any:
    """工具參數欄位裡打的預設值：數字就是數字、true/false 是布林，其餘是字串。"""
    if text is None:
        return None
    if isinstance(text, (int, float, bool)):
        return text
    s = str(text).strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.match(r"^-?\d+$", s):
        return int(s)
    if re.match(r"^-?\d*\.\d+$", s) or re.match(r"^-?\d+\.\d*$", s):
        return float(s)
    return s
