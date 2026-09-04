"""通道：一台相機＋擷取執行緒（擁有 SDK 物件）＋最新影格槽＋命令佇列。

其他執行緒只能透過 `call()` 把工作送到擷取執行緒執行（相機 SDK 大多不是執行緒安全的）。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future
from enum import Enum
from typing import Any, Callable

from vscapture import cameras
from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, ParamSpec
from vscapture.config import ChannelConfig, Roi
from vscapture.frames import Frame, FrameSlot

log = logging.getLogger(__name__)


class ChannelState(str, Enum):
    CLOSED = "closed"
    OPENING = "opening"
    OPEN = "open"
    RUNNING = "running"
    ERROR = "error"


class Channel:
    GRAB_TIMEOUT = 0.5
    MAX_CONSECUTIVE_FAILURES = 30

    def __init__(self, cfg: ChannelConfig, *, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.cfg = cfg
        self.slot = FrameSlot()
        self.camera: Camera | None = None
        self.state = ChannelState.CLOSED
        self.last_error = ""
        self.description: DeviceDescription | None = None
        self.hw_roi_active = False
        self.origin = (0, 0)
        self._on_event = on_event or (lambda kind, data: None)
        self._commands: queue.Queue[tuple[Callable[..., Any], tuple, dict, Future] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._alive = False
        self._failures = 0
        self._fps = 0.0
        self._fps_last = 0.0
        self._fps_count = 0
        self.dropped = 0
        self.idle_paused = False  # 省電暫停中（相機仍開著，下次要影像時自動恢復）
        self.last_request = time.perf_counter()  # 最後一次有人要影像（伺服端 GRAB／串流／拍攝一張）

    @property
    def id(self) -> str:
        return self.cfg.id

    # ---- 執行緒 ----
    def start_thread(self) -> None:
        if self._thread is not None:
            return
        self._alive = True
        self._thread = threading.Thread(target=self._loop, name=f"vsc-cam-{self.cfg.id}", daemon=True)
        self._thread.start()

    def stop_thread(self, join: bool = True) -> None:
        if self._thread is None:
            return
        self._alive = False
        self._commands.put(None)
        if join:
            self.join_thread()

    def join_thread(self, timeout: float = 5.0) -> None:
        """等擷取執行緒收工；`stop_thread(join=False)` 之後由呼叫者統一等（逾時才會累加）。"""
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float | None = 10.0, **kw: Any) -> Any:
        """在擷取執行緒執行 fn(*args, **kw) 並等結果；已在擷取執行緒則直接呼叫。"""
        if threading.current_thread() is self._thread:
            return fn(*args, **kw)
        if self._thread is None:
            self.start_thread()
        fut: Future = Future()
        self._commands.put((fn, args, kw, fut))
        return fut.result(timeout=timeout)

    def _set_state(self, state: ChannelState, error: str = "") -> None:
        changed = state != self.state or error != self.last_error
        self.state, self.last_error = state, error
        if changed:
            self._on_event("channel", {"id": self.cfg.id, "state": state.value, "error": error})

    def _loop(self) -> None:
        while self._alive:
            running = self.state == ChannelState.RUNNING and self.camera is not None and self.camera.trigger_mode != "software"
            try:
                item = self._commands.get(timeout=0.0 if running else 0.05)
            except queue.Empty:
                item = None
            else:
                if item is None:
                    break
                fn, args, kw, fut = item
                try:
                    fut.set_result(fn(*args, **kw))
                except BaseException as exc:  # noqa: BLE001
                    fut.set_exception(exc)
                continue
            if running:
                self._grab_once()
        try:
            self._do_close()
        except Exception:  # noqa: BLE001
            log.exception("通道 %s 關閉相機失敗", self.cfg.id)

    def _grab_once(self) -> None:
        assert self.camera is not None
        try:
            got = self.camera.grab_one(self.GRAB_TIMEOUT)
        except CameraError as exc:
            self._failures += 1
            if self._failures >= self.MAX_CONSECUTIVE_FAILURES:
                self._set_state(ChannelState.ERROR, f"連續取像失敗：{exc}")
                self._try_reopen()
            return
        if got is None:
            return
        self._failures = 0
        image, origin = got
        self.origin = origin
        self._publish(image, origin)

    def _publish(self, image: Any, origin: tuple[int, int]) -> Frame:
        desc = self.description
        full = (desc.sensor_w, desc.sensor_h) if desc and desc.sensor_w else (0, 0)
        frame = self.slot.publish(image, origin=origin, full=full)
        now = time.perf_counter()
        self._fps_count += 1
        if now - self._fps_last >= 1.0:
            self._fps = self._fps_count / (now - self._fps_last) if self._fps_last else float(self._fps_count)
            self._fps_last, self._fps_count = now, 0
        return frame

    def _try_reopen(self) -> None:
        try:
            self._do_close()
            time.sleep(1.0)
            self._do_open()
            self._do_start()
        except Exception as exc:  # noqa: BLE001
            self._set_state(ChannelState.ERROR, f"重新開啟相機失敗：{exc}")

    # ---- 命令（在擷取執行緒執行）----
    def _do_open(self) -> DeviceDescription:
        self._set_state(ChannelState.OPENING)
        try:
            cam = cameras.create(self.cfg.backend)
            desc = cam.open(self.cfg.device_id)
        except Exception as exc:  # noqa: BLE001
            self._set_state(ChannelState.ERROR, str(exc))
            raise
        self.camera, self.description = cam, desc
        errors: dict[str, str] = {}
        values = self.cfg.params.to_values()
        values.update(self.cfg.extras)
        if values:
            try:
                cam.set_params(values)
            except CameraParamError as exc:
                errors.update(exc.errors)
        try:
            self.hw_roi_active, _ = cam.apply_roi(self.cfg.roi, self.cfg.hw_roi)
        except CameraError as exc:
            errors["roi"] = str(exc)
        self._failures = 0
        self._set_state(ChannelState.OPEN, "；".join(f"{k}：{v}" for k, v in errors.items()))
        return desc

    def _do_close(self) -> None:
        cam, self.camera = self.camera, None
        if cam is not None:
            try:
                cam.stop()
            finally:
                cam.close()
        self.slot.clear()
        self._set_state(ChannelState.CLOSED)

    def _do_start(self) -> None:
        if self.camera is None:
            self._do_open()
        assert self.camera is not None
        self.camera.start()
        self._fps_last, self._fps_count = time.perf_counter(), 0
        self._set_state(ChannelState.RUNNING)

    def _do_stop(self) -> None:
        if self.camera is not None:
            self.camera.stop()
        if self.state == ChannelState.RUNNING:
            self._set_state(ChannelState.OPEN)

    # ---- 對外 ----
    def open(self) -> DeviceDescription:
        return self.call(self._do_open)

    def close(self) -> None:
        self.call(self._do_close)

    def start(self) -> None:
        self.idle_paused = False
        self.last_request = time.perf_counter()
        self.call(self._do_start)

    def stop(self) -> None:
        self.idle_paused = False
        self.call(self._do_stop)

    def acquire(self, min_seq: int, timeout: float, *, after_request: bool = True) -> Frame | None:
        """取影格：自由取像／硬體觸發＝等 slot 的 seq ≥ min_seq；軟體觸發＝觸發一張。省電暫停中會先恢復取像。"""
        self.last_request = time.perf_counter()
        if self.idle_paused:
            self.resume_idle()
        cam = self.camera
        if cam is None or self.state != ChannelState.RUNNING:
            return None
        if cam.trigger_mode == "software":
            try:
                image, origin = self.call(cam.snap, timeout, timeout=timeout + 1.0)
            except Exception:  # noqa: BLE001
                return None
            return self.call(self._publish, image, origin, timeout=2.0)
        if not after_request:
            latest = self.slot.latest()
            if latest is not None and latest.seq > min_seq:
                return latest
        return self.slot.wait_for(max(min_seq + 1, self.slot.seq + 1 if after_request else 0), timeout)

    def params(self) -> dict[str, ParamSpec]:
        cam = self.camera
        if cam is None:
            return {}
        return self.call(cam.get_params)

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        cam = self.camera
        if cam is None:
            raise CameraError("相機尚未開啟")
        applied = self.call(cam.set_params, values)
        for key, value in applied.items():
            if hasattr(self.cfg.params, key):
                setattr(self.cfg.params, key, value)
            else:
                self.cfg.extras[key] = value
        return applied

    def apply_roi(self, roi: Roi, hardware: bool) -> tuple[bool, Roi]:
        cam = self.camera
        if cam is None:
            self.cfg.roi, self.cfg.hw_roi = roi, hardware
            return False, roi
        is_hw, effective = self.call(cam.apply_roi, roi, hardware)
        self.hw_roi_active = is_hw
        self.cfg.roi, self.cfg.hw_roi = (effective if is_hw else roi), hardware
        return is_hw, effective

    def pause_idle(self) -> bool:
        """省電暫停：停止取像但不關相機（參數與 ROI 都保留），下次 `acquire()` 會自動恢復。"""
        if self.state != ChannelState.RUNNING:
            return False
        self.idle_paused = True
        try:
            self.call(self._do_stop, timeout=5.0)
        except Exception:  # noqa: BLE001
            self.idle_paused = False
            return False
        log.info("通道 %s 閒置，暫停取像以節省 CPU", self.cfg.id)
        return True

    def resume_idle(self) -> bool:
        if not self.idle_paused:
            return False
        self.idle_paused = False
        try:
            self.call(self._do_start, timeout=10.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("通道 %s 恢復取像失敗：%s", self.cfg.id, exc)
            return False
        return True

    def stats(self) -> dict[str, Any]:
        latest = self.slot.latest()
        return {
            "id": self.cfg.id, "name": self.cfg.name, "state": self.state.value, "error": self.last_error, "seq": self.slot.seq, "fps": round(self._fps, 1),
            "idle_paused": self.idle_paused, "idle_s": round(time.perf_counter() - self.last_request, 1),
            "width": int(latest.image.shape[1]) if latest is not None else None, "height": int(latest.image.shape[0]) if latest is not None else None,
            "hw_roi": self.hw_roi_active, "dropped": self.dropped,
        }

    def hello_dict(self) -> dict[str, Any]:
        """HELLO／CHANNELS 用的通道描述（依目前設定推估送出尺寸）。"""
        desc = self.description
        sw, sh = (desc.sensor_w, desc.sensor_h) if desc and desc.sensor_w else (self.cfg.params.width or 0, self.cfg.params.height or 0)
        roi = self.cfg.roi.clamp(sw, sh) if sw else self.cfg.roi
        w, h = (roi.w, roi.h) if not roi.is_full() else (sw, sh)
        d = max(1, self.cfg.delivery.downscale)
        w, h = w // d, h // d
        native_color = bool(desc.native_color) if desc else (self.cfg.params.pixel_format or "BGR8") != "Mono8"
        mono = self.cfg.delivery.mono or (self.cfg.params.pixel_format or "").startswith("Mono")
        channels = 1 if (mono or not native_color) else 3
        return {
            "id": self.cfg.id, "label": self.cfg.name or self.cfg.id, "driver": self.cfg.backend, "width": int(w), "height": int(h), "channels": channels, "dtype": "u8",
            "pixel_format": "Mono8" if channels == 1 else "BGR8", "roi": {"x": roi.x, "y": roi.y, "w": int(w), "h": int(h)}, "full": {"w": int(sw), "h": int(sh)},
            "mode": self.cfg.delivery.mode, "enabled": self.cfg.enabled, "max_bytes": int(max(1, w) * max(1, h) * channels),
        }
