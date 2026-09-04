"""擷取端核心（無 Qt）：通道集合＋傳輸客戶端＋事件匯流排；桌面 UI 與 headless 模式都用這一層。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from vscapture import __version__, config as configmod, update as updatemod
from vscapture.channel import Channel
from vscapture.config import AppConfig, ChannelConfig
from vscapture.transport.client import TransportClient
from vscapture.update import UpdateInfo

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
        #: 自動更新：idle → downloading → staging → ready →（可套用時）applying／error
        self.update_phase = "idle"
        self.update_received = 0
        self.update_total = 0
        self.update_error = ""
        self.update_staged: Path | None = None
        self.exit_requested = threading.Event()  # 更新程式已接手，主程式該結束了
        self._update_thread: threading.Thread | None = None
        self._update_cancel = threading.Event()
        self.events.subscribe(self._on_own_event)

    # ---- 自動更新 ----
    def _on_own_event(self, kind: str, data: dict[str, Any]) -> None:
        """伺服端宣告有新版時，依設定決定要不要自己下載安裝。"""
        if kind != "update" or "phase" in data:
            return
        info = data.get("info")
        if isinstance(info, UpdateInfo) and info.available and self.cfg.connection.auto_update == "auto":
            self.start_update(install=True)

    @property
    def update_info(self) -> UpdateInfo:
        return self.transport.update

    def update_status(self) -> dict[str, Any]:
        info = self.update_info
        return {
            "phase": self.update_phase, "received": self.update_received, "total": self.update_total, "error": self.update_error,
            "version": info.version, "available": info.available, "size": info.size, "built_at": info.built_at,
            "can_install": updatemod.is_frozen(), "staged": str(self.update_staged or ""),
        }

    def _set_update(self, phase: str, *, error: str = "", received: int | None = None, total: int | None = None) -> None:
        self.update_phase = phase
        self.update_error = error
        if received is not None:
            self.update_received = received
        if total is not None:
            self.update_total = total
        self.events.emit("update", {"phase": phase, "received": self.update_received, "total": self.update_total, "error": error, "version": self.update_info.version})

    def start_update(self, *, install: bool = True) -> bool:
        """背景下載並安裝新版；回 False 表示沒有可用的新版或已經在進行。"""
        info = self.update_info
        if not info.available or (self._update_thread is not None and self._update_thread.is_alive()):
            return False
        self._update_cancel.clear()
        self._update_thread = threading.Thread(target=self._run_update, args=(info, install), name="vsc-update", daemon=True)
        self._update_thread.start()
        return True

    def cancel_update(self) -> None:
        self._update_cancel.set()

    def _run_update(self, info: UpdateInfo, install: bool) -> None:
        try:
            self._set_update("downloading", received=0, total=info.size)
            zip_path = updatemod.download(
                self.transport.pull_update, info,
                on_progress=lambda got, total: self._set_update("downloading", received=got, total=total),
                cancel=self._update_cancel,
            )
            self._set_update("staging")
            self.update_staged = updatemod.stage(zip_path, info.version)
            if not install or not updatemod.is_frozen():
                self._set_update("ready", error="" if install else "已下載，等待套用")
                log.info("擷取端新版 %s 已就緒：%s", info.version, self.update_staged)
                return
            self._set_update("applying")
            updatemod.apply(self.update_staged, restart=True)
            self.exit_requested.set()
        except Exception as exc:  # noqa: BLE001 — 更新失敗不能影響取像
            log.warning("自動更新失敗：%s", exc)
            self._set_update("error", error=str(exc))

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
        self._update_cancel.set()
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
