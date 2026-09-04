"""擷取端核心（無 Qt）：通道集合＋傳輸客戶端＋事件匯流排；桌面 UI 與 headless 模式都用這一層。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from vscapture import __version__, config as configmod
from vscapture.channel import Channel
from vscapture.config import AppConfig, ChannelConfig
from vscapture.transport.client import TransportClient

log = logging.getLogger(__name__)


class EventBus:
    """`subscribe(fn(kind, data))`；`emit` 在呼叫者執行緒逐一呼叫（UI 端請自行轉到主執行緒）。"""

    def __init__(self) -> None:
        self._subs: list[Callable[[str, dict[str, Any]], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs.append(fn)

    def unsubscribe(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        with self._lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(kind, data)
            except Exception:  # noqa: BLE001
                log.exception("事件處理失敗：%s", kind)


class CaptureEngine:
    def __init__(self, cfg: AppConfig, *, config_path: Path | None = None) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.events = EventBus()
        self.channels: dict[str, Channel] = {}
        self._order: list[str] = []
        self.transport = TransportClient(self, cfg.connection, version=__version__)
        self._started = False

    # ---- 生命週期 ----
    def start(self, *, connect: bool | None = None) -> None:
        if self._started:
            return
        self._started = True
        for ccfg in self.cfg.channels:
            self._add(ccfg)
        for ch in self.channels.values():
            if ch.cfg.enabled:
                self._open_and_start(ch)
        if connect if connect is not None else self.cfg.connection.auto_connect:
            self.connect()

    def stop(self) -> None:
        self.transport.stop()
        for ch in list(self.channels.values()):
            try:
                ch.stop_thread()
            except Exception:  # noqa: BLE001
                log.exception("停止通道 %s 失敗", ch.id)
        self._started = False

    def connect(self) -> None:
        self.transport.update_config(self.cfg.connection)
        self.transport.start()

    def reload(self, cfg: AppConfig) -> None:
        """依新的設定重建：關閉所有相機與連線，重新建立通道；原本有連線就重新連。"""
        was_connected = self.transport.state.value != "disconnected"
        self.stop()
        self.channels.clear()
        self._order.clear()
        self.cfg = cfg
        self.transport.update_config(cfg.connection)
        self.start(connect=was_connected or None)

    def disconnect(self) -> None:
        self.transport.stop()

    # ---- 通道 ----
    def _add(self, ccfg: ChannelConfig) -> Channel:
        ch = Channel(ccfg, on_event=self.events.emit)
        self.channels[ccfg.id] = ch
        self._order.append(ccfg.id)
        ch.start_thread()
        return ch

    def _open_and_start(self, ch: Channel) -> None:
        try:
            ch.open()
            ch.start()
        except Exception as exc:  # noqa: BLE001 — 開不起來只標 ERROR，不影響其他通道
            log.warning("通道 %s 開啟失敗：%s", ch.id, exc)

    def add_channel(self, ccfg: ChannelConfig) -> Channel:
        if ccfg.id in self.channels:
            raise ValueError(f"通道 id 重複：{ccfg.id}")
        self.cfg.channels.append(ccfg)
        ch = self._add(ccfg)
        if ccfg.enabled and ccfg.device_id:
            self._open_and_start(ch)
        self.transport.send_channels()
        return ch

    def remove_channel(self, cid: str) -> None:
        ch = self.channels.get(cid)
        if ch is None:
            return
        ch.stop_thread()
        # 索引只增不減：留一個停用的墓碑給伺服端，在途 GRAB 不會錯位
        ch.cfg.enabled = False
        self.cfg.channels = [c for c in self.cfg.channels if c.id != cid]
        self.transport.send_channels()

    def update_channel(self, cid: str, ccfg: ChannelConfig, *, reopen: bool = False) -> None:
        ch = self.channels.get(cid)
        if ch is None:
            raise KeyError(cid)
        ch.cfg = ccfg
        self.cfg.channels = [ccfg if c.id == cid else c for c in self.cfg.channels]
        if reopen:
            try:
                ch.close()
            except Exception:  # noqa: BLE001
                pass
            if ccfg.enabled and ccfg.device_id:
                self._open_and_start(ch)
        self.transport.send_channels()

    def channel_index(self, cid: str) -> int:
        return self._order.index(cid)

    def channel_id(self, index: int) -> str:
        return self._order[index] if 0 <= index < len(self._order) else ""

    def hello_channels(self) -> list[dict[str, Any]]:
        return [self.channels[cid].hello_dict() for cid in self._order if cid in self.channels]

    # ---- 設定 ----
    def save_config(self) -> Path:
        return configmod.save(self.cfg, self.config_path)

    def status(self) -> dict[str, Any]:
        return {"connection": self.transport.stats(), "channels": [self.channels[cid].stats() for cid in self._order if cid in self.channels]}
