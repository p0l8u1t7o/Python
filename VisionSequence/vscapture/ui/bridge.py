"""引擎 ⇄ Qt 的橋：引擎事件與記錄轉成 signal（進 UI 執行緒），耗時的引擎操作用 `run_async` 丟到執行緒池。"""

from __future__ import annotations

import itertools
import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from vscapture.engine import CaptureEngine

log = logging.getLogger(__name__)


class _LogHandler(logging.Handler):
    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.log.emit(record.levelno, self.format(record))
        except Exception:  # noqa: BLE001 — 記錄不能把程式弄掛
            pass


class _Job(QRunnable):
    def __init__(self, bridge: EngineBridge, job_id: int, fn: Callable[..., Any], args: tuple, kw: dict) -> None:
        super().__init__()
        self.bridge, self.job_id, self.fn, self.args, self.kw = bridge, job_id, fn, args, kw
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kw)
        except BaseException as exc:  # noqa: BLE001
            self.bridge._job_failed.emit(self.job_id, str(exc) or exc.__class__.__name__)
            return
        self.bridge._job_done.emit(self.job_id, result)


class EngineBridge(QObject):
    """訂閱 `engine.events`，把事件以 signal 送進 UI 執行緒；也提供 `run_async(fn, *args, on_done=, on_error=)`。"""

    connection = Signal(object)  # {"state", "detail"}
    channel = Signal(object)  # {"id", "state", "error"}
    stream = Signal(object)  # {"id", "enabled"}
    log = Signal(int, str)  # (levelno, 已格式化文字)
    _job_done = Signal(int, object)
    _job_failed = Signal(int, str)

    def __init__(self, engine: CaptureEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._callbacks: dict[int, tuple[Callable[[Any], None] | None, Callable[[str], None] | None]] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._job_done.connect(self._on_done)
        self._job_failed.connect(self._on_failed)
        engine.events.subscribe(self._on_engine_event)
        self.handler = _LogHandler(self)
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(self.handler)

    def close(self) -> None:
        self.engine.events.unsubscribe(self._on_engine_event)
        logging.getLogger().removeHandler(self.handler)
        self.pool.waitForDone(3000)

    # 任何執行緒
    def _on_engine_event(self, kind: str, data: dict[str, Any]) -> None:
        sig = {"connection": self.connection, "channel": self.channel, "stream": self.stream}.get(kind)
        if sig is not None:
            sig.emit(dict(data))

    def run_async(self, fn: Callable[..., Any], *args: Any, on_done: Callable[[Any], None] | None = None, on_error: Callable[[str], None] | None = None, **kw: Any) -> int:
        """在執行緒池執行 fn(*args, **kw)；完成後在 UI 執行緒呼叫 on_done(result) 或 on_error(訊息)。"""
        job_id = next(self._ids)
        with self._lock:
            self._callbacks[job_id] = (on_done, on_error)
        self.pool.start(_Job(self, job_id, fn, args, kw))
        return job_id

    @Slot(int, object)
    def _on_done(self, job_id: int, result: Any) -> None:
        with self._lock:
            on_done, _ = self._callbacks.pop(job_id, (None, None))
        if on_done is not None:
            try:
                on_done(result)
            except Exception:  # noqa: BLE001
                log.exception("背景工作的回呼失敗")

    @Slot(int, str)
    def _on_failed(self, job_id: int, message: str) -> None:
        with self._lock:
            _, on_error = self._callbacks.pop(job_id, (None, None))
        if on_error is not None:
            on_error(message)
        else:
            log.warning("背景工作失敗：%s", message)
