"""Modbus 觸發：PLC 寫一個旗標位址，平台就跑一次流程。

從站（`modbus_server`）模式下，PLC 是主站——它只會「寫暫存器」，不會呼叫我們的 HTTP／TCP。
沒有這一層的話，PLC 把觸發旗標寫進來也不會有任何事發生，整條線只能改用連續模式輪詢
（每一輪都取像，白白吃掉相機頻寬與 CPU）。主站（`modbus_tcp`）模式同樣可用：輪詢 PLC 自己的
暫存器當觸發源。

握手（`trigger_clear` 與 `trigger_done_address` 都是選填）：

    PLC:  trigger := 1
    平台: 看到 → 清 trigger（trigger_clear）→ 跑流程 → 流程自己用「寫入 Modbus」送結果
          → done := 1（trigger_done_address）
    PLC:  看到 done → 讀結果 → done := 0

一條連線一條執行緒，只做「讀一個位址、必要時跑一次流程」；不碰執行緒池的熱路徑，
流程本身照樣走 runner（統計、SSE、歷史都與其他觸發來源一致）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

#: 輪詢間隔的下限（再快也沒有意義，只會空轉）。
MIN_INTERVAL_MS = 10
DEFAULT_INTERVAL_MS = 50
#: 讀取連續失敗時的退避上限（PLC 斷線不該讓日誌洗版）。
MAX_BACKOFF_S = 5.0
#: 流程列多久回資料庫確認一次（沿用連續模式的做法，熱路徑不查 DB）。
FLOW_REFRESH_S = 2.0


def config_of(config: dict[str, Any]) -> dict[str, Any] | None:
    """從連線設定挑出觸發設定；沒有 `trigger_address` 或 `trigger_flow` 就是沒開。"""
    address = str(config.get("trigger_address") or "").strip()
    flow = str(config.get("trigger_flow") or "").strip()
    if not address or not flow:
        return None
    try:
        interval = int(config.get("trigger_interval_ms") or DEFAULT_INTERVAL_MS)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_MS
    mode = str(config.get("trigger_mode") or "rising").lower()
    return {
        "address": address,
        "flow": flow,
        "interval_ms": max(MIN_INTERVAL_MS, interval),
        # rising＝0 變成非零才觸發（PLC 要自己清旗標或交給 trigger_clear）；
        # nonzero＝只要讀到非零就一直觸發（旗標當「連續檢測中」用）。
        "mode": "nonzero" if mode == "nonzero" else "rising",
        "clear": bool(config.get("trigger_clear", True)),
        "done": str(config.get("trigger_done_address") or "").strip(),
        "recipe": str(config.get("trigger_recipe") or "").strip(),
    }


class TriggerLoop(threading.Thread):
    """一條連線一個觸發迴圈。`writer` 只要有 `read()`／`write()` 就能用。"""

    def __init__(self, writer, settings: dict[str, Any]) -> None:
        super().__init__(name=f"modbus-trigger-{writer.name or writer.kind}", daemon=True)
        self.writer = writer
        self.settings = settings
        self.fired = 0
        self.errors = 0
        self.last_error = ""
        self.last_fired_at = 0.0
        self._halt = threading.Event()
        self._flow = None
        self._flow_at = 0.0

    def stop(self) -> None:
        self._halt.set()

    def status(self) -> dict[str, Any]:
        return {
            "address": self.settings["address"], "flow": self.settings["flow"], "mode": self.settings["mode"],
            "interval_ms": self.settings["interval_ms"], "running": self.is_alive(), "fired": self.fired,
            "errors": self.errors, "last_error": self.last_error, "last_fired_at": self.last_fired_at,
        }

    # -- 迴圈 ---------------------------------------------------------------
    def run(self) -> None:
        address = self.settings["address"]
        interval = self.settings["interval_ms"] / 1000.0
        rising = self.settings["mode"] == "rising"
        last_on = False
        backoff = 0.0
        while not self._halt.wait(backoff or interval):
            try:
                value = bool(self.writer.read([address], quiet=True).get(address))
                backoff = 0.0
            except Exception as exc:  # noqa: BLE001 — PLC 斷線是常態，退避後繼續試
                self.errors += 1
                self.last_error = str(exc)[:200]
                backoff = min(MAX_BACKOFF_S, max(interval * 4, (backoff or interval) * 2))
                continue
            fire = value and (not rising or not last_on)
            last_on = value
            if fire:
                self._fire()

    def _fire(self) -> None:
        from apps.vision import trace

        started = time.perf_counter()
        settings = self.settings
        try:
            if settings["clear"]:  # 先清旗標再跑，跑很久也不會被重複觸發
                self.writer.write({settings["address"]: 0})
            flow = self._resolve_flow()
            if flow is None:
                raise LookupError(f"流程 '{settings['flow']}' 不存在或已停用")
            report = self._run(flow)
            self.fired += 1
            self.last_fired_at = time.time()
            if settings["done"]:
                self.writer.write({settings["done"]: 1})
            trace.record(
                "modbus", f"觸發 {settings['address']} → {flow.name}：{report.status}", direction="in",
                name=self.writer.name or self.writer.kind, ok=report.status != "failed",
                ms=(time.perf_counter() - started) * 1000,
                detail={"flow": flow.name, "run_id": report.id, "status": report.status, "outputs": report.outputs, "error": report.error},
            )
        except Exception as exc:  # noqa: BLE001 — 觸發失敗只記錄，迴圈要活著
            self.errors += 1
            self.last_error = str(exc)[:200]
            log.warning("Modbus 觸發失敗（%s）：%s", self.writer.name, self.last_error)
            trace.record("modbus", f"觸發 {settings['address']} 失敗", direction="in", name=self.writer.name or self.writer.kind,
                         ok=False, ms=(time.perf_counter() - started) * 1000, detail={"error": self.last_error})

    def _resolve_flow(self):
        """流程列快取 FLOW_REFRESH_S 秒（PLC 每 50 ms 觸發也不會每次查 DB）。"""
        now = time.monotonic()
        if self._flow is not None and now - self._flow_at < FLOW_REFRESH_S:
            return self._flow
        from django.db import close_old_connections

        from apps.vision.models import Flow

        ident = self.settings["flow"]
        try:
            qs = Flow.objects.filter(pk=int(ident)) if ident.isdigit() else Flow.objects.filter(name=ident)
            self._flow = qs.filter(is_enabled=True).first()
        finally:
            close_old_connections()
        self._flow_at = now
        return self._flow

    def _run(self, flow):
        from django.db import close_old_connections

        from apps.vision.runner import runner

        try:
            return runner.run_sync(flow, trigger="modbus", recipe=self.settings["recipe"] or None)
        finally:
            close_old_connections()


# ---------------------------------------------------------------------------
# 註冊表（一條連線最多一個迴圈）
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_loops: dict[int, TriggerLoop] = {}


def sync(connection_id: int, writer, config: dict[str, Any]) -> TriggerLoop | None:
    """依設定啟動／停止該連線的觸發迴圈；設定沒變就沿用現有的。回目前的迴圈。"""
    settings = config_of(config or {})
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
    log.info("Modbus 觸發已啟動：%s %s → 流程 %s", writer.name, settings["address"], settings["flow"])
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
