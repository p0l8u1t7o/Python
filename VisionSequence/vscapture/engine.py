"""擷取端核心（無 Qt）：通道集合＋傳輸客戶端＋事件匯流排；桌面 UI 與 headless 模式都用這一層。"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from vscapture import __version__, config as configmod, update as updatemod
from vscapture.channel import Channel
from vscapture.config import AppConfig, ChannelConfig
from vscapture.recorder import RecordConfig, Recorder
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
        #: 介面是否顯示中（縮到系統匣或最小化時為 False：沒人在看預覽，就不必一直取像）
        self.ui_visible = True
        self._idle_thread: threading.Thread | None = None
        self._idle_stop = threading.Event()
        self._recorders: dict[str, Recorder] = {}
        self.events.subscribe(self._on_own_event)

    # ---- 省電：閒置時停止取像 ----
    def set_ui_visible(self, visible: bool) -> None:
        """介面顯示／縮到系統匣。看不到預覽時，只有伺服端還在要影像才需要繼續取像。"""
        if visible == self.ui_visible:
            return
        self.ui_visible = visible
        for ch in self.channels.values():
            ch.last_request = max(ch.last_request, time.perf_counter() if visible else ch.last_request)
        if visible:  # 回到前景：預覽要有畫面，馬上恢復
            for ch in self.channels.values():
                if ch.idle_paused and ch.cfg.preview and ch.cfg.enabled:
                    ch.resume_idle()

    def _wants_frames(self, ch: Channel) -> bool:
        """有人要這個通道的影像嗎：介面在看預覽、伺服端開了串流，或剛剛才要過。"""
        if self.ui_visible and ch.cfg.preview:
            return True
        if self.transport.is_streaming(ch.id):
            return True
        rec = self._recorders.get(ch.id)
        if rec is not None and rec.status.active:
            return True
        idle_s = float(self.cfg.connection.idle_stop_s or 0)
        return idle_s <= 0 or (time.perf_counter() - ch.last_request) < idle_s

    def _idle_loop(self) -> None:
        while not self._idle_stop.wait(1.0):
            if float(self.cfg.connection.idle_stop_s or 0) <= 0 and self.ui_visible:
                continue
            for ch in list(self.channels.values()):
                try:
                    if ch.state.value == "running" and not self._wants_frames(ch):
                        ch.pause_idle()
                except Exception:  # noqa: BLE001 — 看門狗不能把程式弄掛
                    log.exception("閒置檢查失敗：%s", ch.id)

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
        if self._idle_thread is None:
            self._idle_stop.clear()
            self._idle_thread = threading.Thread(target=self._idle_loop, name="vsc-idle", daemon=True)
            self._idle_thread.start()
        if connect if connect is not None else self.cfg.connection.auto_connect:
            self.connect()

    def stop(self) -> None:
        self._idle_stop.set()
        if self._idle_thread is not None:
            self._idle_thread.join(timeout=3.0)
            self._idle_thread = None
        self._update_cancel.set()
        self.stop_recording()
        self.transport.stop()
        # 先叫所有通道停，再一起等：逐條 stop_thread(join=True) 會讓每條的 5 秒逾時累加，
        # 四個通道最糟要 20 秒才關得掉（使用者看到的就是「視窗不見了，行程還在」）。
        channels = list(self.channels.values())
        for ch in channels:
            try:
                ch.stop_thread(join=False)
            except Exception:  # noqa: BLE001
                log.exception("停止通道 %s 失敗", ch.id)
        for ch in channels:
            ch.join_thread(timeout=5.0)
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

    # ---- 錄影 ----
    def _record_cfg(self) -> RecordConfig:
        raw = self.cfg.recording
        return RecordConfig(
            folder=raw.folder, codec=raw.codec, fps_divisor=raw.fps_divisor, scale=raw.scale,
            max_minutes=raw.max_minutes, server_folder=raw.server_folder, auto_upload=raw.auto_upload,
        )

    @staticmethod
    def _nominal_fps(ch: Channel) -> float:
        if ch.cfg.params.fps:
            return float(ch.cfg.params.fps)
        try:
            specs = ch.params()
            spec = specs.get("fps")
            if spec is not None and spec.value:
                return float(spec.value)
        except Exception:  # noqa: BLE001
            pass
        return 30.0

    def start_recording(self, channel_ids: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
        """開始錄影；每通道一個 Recorder 執行緒，只讀最新影格並自行丟幀。"""
        ids = list(channel_ids or self._order)
        started: list[str] = []
        errors: dict[str, str] = {}
        for cid in ids:
            ch = self.channels.get(cid)
            if ch is None:
                errors[cid] = "No such channel"
                continue
            if not ch.cfg.enabled:
                errors[cid] = "Channel disabled"
                continue
            try:
                if ch.idle_paused:
                    ch.resume_idle()
                elif ch.state.value == "open":
                    ch.start()
            except Exception as exc:  # noqa: BLE001
                errors[cid] = str(exc)
                continue
            rec = self._recorders.get(cid)
            if rec is not None and rec.status.active:
                started.append(cid)
                continue
            rec = Recorder(cid, ch.latest_frame_for_recording, self._record_cfg(), nominal_fps=self._nominal_fps(ch))
            self._recorders[cid] = rec
            rec.start()
            started.append(cid)
        self.events.emit("recording", {"items": self.recording_status()["items"], "started": started, "errors": errors})
        return {"started": started, "errors": errors}

    def _auto_upload_recording(self, path: str) -> None:
        """錄完自動上傳；走傳輸控制佇列，不插入影格傳送路徑。"""
        if not path:
            return
        try:
            self.transport.upload_file(Path(path))
        except Exception as exc:  # noqa: BLE001
            log.warning("recording auto upload failed: %s", exc)

    def stop_recording(self, channel_ids: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
        ids = list(channel_ids or list(self._recorders))
        stopped: list[str] = []
        for cid in ids:
            rec = self._recorders.get(cid)
            if rec is None:
                continue
            rec.stop()
            stopped.append(cid)
            path = rec.status.path
            if self.cfg.recording.auto_upload and path and not self.cfg.recording.server_folder:
                threading.Thread(target=self._auto_upload_recording, args=(path,), name=f"vsc-upload-{cid}", daemon=True).start()
        self.events.emit("recording", {"items": self.recording_status()["items"], "stopped": stopped})
        return {"stopped": stopped}

    def recording_status(self) -> dict[str, Any]:
        return {"items": {cid: rec.status.to_dict() for cid, rec in sorted(self._recorders.items())}}

    # ---- 設定 ----
    def save_config(self) -> Path:
        return configmod.save(self.cfg, self.config_path)

    def status(self) -> dict[str, Any]:
        return {
            "connection": self.transport.stats(),
            "channels": [self.channels[cid].stats() for cid in self._order if cid in self.channels],
            "recording": self.recording_status(),
        }
