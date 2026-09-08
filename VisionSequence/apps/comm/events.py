"""站台事件回報與心跳：讓上位機不必輪詢也知道這一站在做什麼。

現場最常被問的兩件事——「平台起來了嗎」與「現在在忙嗎」。以前只能靠上位機每秒打一次
`STATUS`，或是在每條流程裡接一顆「寫入 Modbus」。這一層把站台層的事件（伺服器就緒、
流程忙／閒、影像來源上下線、引擎鎖定／解除）直接送到指定的連線，另外可以每 N 毫秒送一則心跳。

**每一片的結果不走這裡**：事件匯流排（`runner.bus`）只留最近 500 則，忙的時候會漏，
漏掉一片的判定是不能接受的。逐片回送請用流程的結果回送規則（`Flow.comm`）或圖裡的
「寫入 Modbus」，那兩條路是同步的、跑完就送。

心跳有兩種形態：文字連線送一段排好版的文字（上位機當看門狗用），Modbus 連線把一個
遞增的計數寫進指定位址（PLC 的看門狗就是這樣做的，數字停了就知道平台掛了）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

#: 可回報的事件（封閉集合）。刻意不含「每一片的結果」，理由見模組說明。
KINDS = ("server_ready", "flow_busy", "flow_idle", "source_connected", "source_lost", "lock", "unlock")
#: 心跳的下限（再密只是佔住連線的寫入鎖，產線的寫入會被排在後面）。
MIN_HEARTBEAT_MS = 200
DEFAULT_TEMPLATE = "{event};{id}"
DEFAULT_HEARTBEAT = "ALIVE;{station}"
#: Modbus 心跳的計數上限（16 位元有號暫存器裝得下）。
COUNTER_MAX = 32767


def settings_of(config: dict[str, Any]) -> dict[str, Any] | None:
    """連線設定 → 事件回報設定；沒選事件也沒開心跳就是沒開。"""
    config = config or {}
    wanted = config.get("events")
    kinds = [k for k in (wanted if isinstance(wanted, list) else []) if k in KINDS]
    try:
        beat = int(config.get("heartbeat_ms") or 0)
    except (TypeError, ValueError):
        beat = 0
    beat = max(MIN_HEARTBEAT_MS, beat) if beat > 0 else 0
    address = str(config.get("heartbeat_address") or "").strip()
    if not kinds and not beat:
        return None
    return {
        "kinds": kinds,
        "template": str(config.get("event_template") or "") or DEFAULT_TEMPLATE,
        "heartbeat_ms": beat,
        "heartbeat_payload": str(config.get("heartbeat_payload") or "") or DEFAULT_HEARTBEAT,
        "heartbeat_address": address,
    }


def translate(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """事件匯流排的一則 → (回報的種類, 欄位)。認不得的事件回 None。純函式，好測。"""
    kind = str(event.get("type") or "")
    if kind == "server_ready":
        return "server_ready", {"id": event.get("station_id", ""), "name": event.get("station_id", ""), "version": event.get("version", "")}
    if kind == "run_started":
        return "flow_busy", {"id": event.get("flow_id", ""), "run_id": event.get("run_id", "")}
    if kind == "run_finished":
        run = event.get("run") or {}
        return "flow_idle", {"id": event.get("flow_id", ""), "run_id": run.get("id", ""),
                             "status": run.get("status", ""), "judge": (run.get("outputs") or {}).get("judge", "")}
    if kind in ("source_connected", "source_lost"):
        return kind, {"id": event.get("client", ""), "name": event.get("client", ""), "reason": event.get("reason", "")}
    if kind == "lock":
        lock = event.get("lock") or {}
        held = bool(lock.get("locked"))
        return ("lock" if held else "unlock"), {"id": lock.get("holder", ""), "reason": lock.get("reason", "")}
    return None


class EventLoop(threading.Thread):
    """一條連線一個事件迴圈：訂閱事件匯流排，加上自己的心跳計時。"""

    def __init__(self, writer, settings: dict[str, Any]) -> None:
        super().__init__(name=f"events-{writer.name or writer.kind}", daemon=True)
        self.writer = writer
        self.settings = settings
        self.sent = 0
        self.beats = 0
        self.errors = 0
        self.last_error = ""
        self.last_sent_at = 0.0
        self._counter = 0
        self._halt = threading.Event()
        #: 訂閱起點（迴圈起來之後才有值）；只報從那時起發生的事。
        self.since: int | None = None

    def stop(self) -> None:
        self._halt.set()

    def status(self) -> dict[str, Any]:
        return {
            "events": list(self.settings["kinds"]), "heartbeat_ms": self.settings["heartbeat_ms"],
            "running": self.is_alive(), "sent": self.sent, "beats": self.beats,
            "errors": self.errors, "last_error": self.last_error, "last_sent_at": self.last_sent_at,
        }

    # -- 迴圈 ---------------------------------------------------------------
    def run(self) -> None:
        from apps.vision.runner import bus

        since = self.since = bus.seq  # 只報從現在起發生的事（重開連線不該把歷史重播一遍）
        interval = self.settings["heartbeat_ms"] / 1000.0
        next_beat = time.monotonic() + interval if interval else 0.0
        while not self._halt.is_set():
            wait = 1.0
            if interval:
                wait = max(0.01, min(wait, next_beat - time.monotonic()))
            since, items = bus.wait(since, wait)
            if self._halt.is_set():
                return
            for event in items:
                pair = translate(event)
                if pair is not None and pair[0] in self.settings["kinds"]:
                    self._send(*pair)
            if interval and time.monotonic() >= next_beat:
                self._beat()
                now = time.monotonic()
                next_beat += interval
                if next_beat < now:  # 睡太久（連線卡住）就重新對時，不要補送一串
                    next_beat = now + interval

    # -- 送出 ---------------------------------------------------------------
    def _values(self, kind: str, fields: dict[str, Any]) -> dict[str, Any]:
        from django.conf import settings as django_settings

        return {
            "event": kind, "id": "", "name": "", "reason": "", "status": "", "judge": "", "run_id": "",
            "station": django_settings.VISION.get("STATION_ID", ""), "ts": int(time.time()), **fields,
        }

    def _send(self, kind: str, fields: dict[str, Any]) -> None:
        from apps.comm.rules import render

        values = self._values(kind, fields)
        try:
            self.writer.send_text(render(self.settings["template"], values), quiet=True)
            self.sent += 1
            self.last_sent_at = time.time()
        except Exception as exc:  # noqa: BLE001 — 上位機沒開著不該讓事件迴圈死掉
            self.errors += 1
            self.last_error = str(exc)[:200]

    def _beat(self) -> None:
        from apps.comm.rules import render

        try:
            if self.settings["heartbeat_address"]:
                # PLC 的看門狗：一個遞增的計數，數字停了就知道平台掛了
                self._counter = self._counter % COUNTER_MAX + 1
                self.writer.write({self.settings["heartbeat_address"]: self._counter}, quiet=True)
            else:
                self.writer.send_text(render(self.settings["heartbeat_payload"], self._values("heartbeat", {})), quiet=True)
            self.beats += 1
            self.last_sent_at = time.time()
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self.last_error = str(exc)[:200]


# ---------------------------------------------------------------------------
# 註冊表（一條連線最多一個迴圈）
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_loops: dict[int, EventLoop] = {}


def sync(connection_id: int, writer, config: dict[str, Any]) -> EventLoop | None:
    """依設定啟動／停止該連線的事件迴圈；設定沒變就沿用現有的。"""
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
        loop = _loops[connection_id] = EventLoop(writer, settings)
    loop.start()
    log.info("事件回報已啟動：%s（%s 種事件，心跳 %s ms）", writer.name, len(settings["kinds"]), settings["heartbeat_ms"])
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
