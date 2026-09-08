"""觸發輪詢：設備寫一個位址，平台就照規則表做事。

從站（`modbus_server`）模式下，PLC 是主站——它只會「寫暫存器」，不會呼叫我們的 HTTP／TCP。
沒有這一層的話，PLC 把觸發旗標寫進來也不會有任何事發生，整條線只能改用連續模式輪詢
（每一輪都取像，白白吃掉相機頻寬與 CPU）。主站（`modbus_tcp`）模式同樣可用：輪詢 PLC 自己的
暫存器當觸發源。

**一條連線一張規則表**（`apps/comm/rules.py`）：每一列是「哪個位址怎麼變 → 做什麼」，
所以同一台控制器可以一個位址觸發檢測、另一個位址換配方、再一個位址鎖住硬體。
舊的扁平 `trigger_*` 設定由 `rules.rules_of()` 包成單一規則，既有站台不必改設定。

握手（每條規則各自的 `clear` 與 `done`，都是選填）：

    PLC:  trigger := 1
    平台: 看到 → 清 trigger（clear）→ 跑流程 → 流程自己用「寫入 Modbus」送結果
          → done := 1（done）
    PLC:  看到 done → 讀結果 → done := 0

一條連線一條執行緒，每輪只做一次 `read()` 把所有規則要看的位址一起讀回來；不碰執行緒池的熱路徑，
流程本身照樣走 runner（統計、SSE、歷史都與其他觸發來源一致）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from apps.comm import rules as rulemod

log = logging.getLogger(__name__)

#: 輪詢間隔的下限（再快也沒有意義，只會空轉）。
MIN_INTERVAL_MS = 10
DEFAULT_INTERVAL_MS = 50
#: 讀取連續失敗時的退避上限（PLC 斷線不該讓日誌洗版）。
MAX_BACKOFF_S = 5.0
#: 流程列多久回資料庫確認一次（沿用連續模式的做法，熱路徑不查 DB）。
FLOW_REFRESH_S = 2.0


def settings_of(config: dict[str, Any]) -> dict[str, Any] | None:
    """連線設定 → 輪詢設定；沒有任何「值」規則就是沒開（文字規則不需要輪詢）。"""
    listed = [r for r in rulemod.rules_of(config or {}) if r.source == "value"]
    if not listed:
        return None
    try:
        interval = int((config or {}).get("trigger_interval_ms") or DEFAULT_INTERVAL_MS)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_MS
    return {"interval_ms": max(MIN_INTERVAL_MS, interval), "rules": listed}


class TriggerLoop(threading.Thread):
    """一條連線一個輪詢迴圈。`writer` 只要有 `read()`／`write()` 就能用。"""

    def __init__(self, writer, settings: dict[str, Any]) -> None:
        super().__init__(name=f"trigger-{writer.name or writer.kind}", daemon=True)
        self.writer = writer
        self.settings = settings
        self.rules: list[rulemod.Rule] = list(settings["rules"])
        self.fired = 0
        self.errors = 0
        self.last_error = ""
        self.last_fired_at = 0.0
        self._counts: dict[str, int] = {r.id: 0 for r in self.rules}
        self._previous: dict[str, Any] = {}
        self._halt = threading.Event()
        self._flows: dict[str, tuple[Any, float]] = {}

    def stop(self) -> None:
        self._halt.set()

    def status(self) -> dict[str, Any]:
        """連線狀態的 `trigger` 欄。第一條規則的位址與流程留在頂層，舊的整合端不用改。"""
        first = self.rules[0]
        return {
            "address": first.address, "flow": first.flow, "mode": first.mode,
            "interval_ms": self.settings["interval_ms"], "running": self.is_alive(), "fired": self.fired,
            "errors": self.errors, "last_error": self.last_error, "last_fired_at": self.last_fired_at,
            "rules": [
                {"id": r.id, "label": r.label(), "address": r.address, "mode": r.mode,
                 "action": r.action, "flow": r.flow, "fired": self._counts.get(r.id, 0)}
                for r in self.rules
            ],
        }

    # -- 迴圈 ---------------------------------------------------------------
    def run(self) -> None:
        addresses = rulemod.watched_addresses(self.rules)
        interval = self.settings["interval_ms"] / 1000.0
        backoff = 0.0
        while not self._halt.wait(backoff or interval):
            try:
                values = self.writer.read(addresses, quiet=True)
                backoff = 0.0
            except Exception as exc:  # noqa: BLE001 — PLC 斷線是常態，退避後繼續試
                self.errors += 1
                self.last_error = str(exc)[:200]
                backoff = min(MAX_BACKOFF_S, max(interval * 4, (backoff or interval) * 2))
                continue
            for rule in self.rules:
                current = values.get(rule.address)
                if rulemod.match_value(rule, self._previous.get(rule.address), current):
                    self._fire(rule, current)
            self._previous = dict(values)

    def _fire(self, rule: rulemod.Rule, value: Any) -> None:
        from apps.vision import trace

        started = time.perf_counter()
        try:
            if rule.clear:  # 先清旗標再做事，跑很久也不會被重複觸發
                self.writer.write({rule.address: 0})
                self._previous[rule.address] = 0
            outcome = self._act(rule, {"trigger_value": value})
            self.fired += 1
            self._counts[rule.id] = self._counts.get(rule.id, 0) + 1
            self.last_fired_at = time.time()
            if rule.done:
                self.writer.write({rule.done: 1})
            trace.record(
                "modbus", f"Trigger {rule.label()}: {outcome.get('summary', '')}".strip(), direction="in",
                name=self.writer.name or self.writer.kind, ok=bool(outcome.get("ok", True)),
                ms=(time.perf_counter() - started) * 1000, detail=outcome.get("detail"),
            )
        except Exception as exc:  # noqa: BLE001 — 觸發失敗只記錄，迴圈要活著
            self.errors += 1
            self.last_error = str(exc)[:200]
            log.warning("觸發規則失敗（%s／%s）：%s", self.writer.name, rule.label(), self.last_error)
            trace.record("modbus", f"Trigger {rule.label()} failed", direction="in", name=self.writer.name or self.writer.kind,
                         ok=False, ms=(time.perf_counter() - started) * 1000, detail={"error": self.last_error})

    def _act(self, rule: rulemod.Rule, context: dict[str, Any]) -> dict[str, Any]:
        """執行規則的動作（測試把這個換掉就不必真的跑流程）。"""
        from django.db import close_old_connections

        try:
            return rulemod.fire(rule, context, trigger="modbus", find_flow=self._resolve_flow)
        finally:
            close_old_connections()

    def _resolve_flow(self, ident: str):
        """流程列快取 FLOW_REFRESH_S 秒（PLC 每 50 ms 觸發也不會每次查 DB）。"""
        now = time.monotonic()
        cached = self._flows.get(ident)
        if cached is not None and now - cached[1] < FLOW_REFRESH_S:
            return cached[0]
        from django.db import close_old_connections

        try:
            flow = rulemod.find_flow(ident)
        finally:
            close_old_connections()
        self._flows[ident] = (flow, now)
        return flow


# ---------------------------------------------------------------------------
# 註冊表（一條連線最多一個迴圈）
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_loops: dict[int, TriggerLoop] = {}


def sync(connection_id: int, writer, config: dict[str, Any]) -> TriggerLoop | None:
    """依設定啟動／停止該連線的輪詢迴圈；設定沒變就沿用現有的。回目前的迴圈。"""
    settings = settings_of(config or {})
    with _lock:
        current = _loops.get(connection_id)
        if current is not None and current.is_alive() and settings == current.settings and current.writer is writer:
            return current
        if current is not None:
            current.stop()
            _loops.pop(connection_id, None)
        if settings is None:
            return None
        loop = _loops[connection_id] = TriggerLoop(writer, settings)
    loop.start()
    log.info("觸發輪詢已啟動：%s（%s 條規則，每 %s ms）", writer.name, len(settings["rules"]), settings["interval_ms"])
    return loop


def stop(connection_id: int) -> None:
    with _lock:
        loop = _loops.pop(connection_id, None)
    if loop is not None:
        loop.stop()


def stop_all() -> None:
    with _lock:
        loops = list(_loops.values())
        _loops.clear()
    for loop in loops:
        loop.stop()


def status(connection_id: int) -> dict[str, Any] | None:
    with _lock:
        loop = _loops.get(connection_id)
    return loop.status() if loop is not None else None
