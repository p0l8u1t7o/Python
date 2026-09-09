"""影像來源「擷取端相機」：向 hub 要一張（依需求）或取串流最新影格。"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from apps.core.errors import ValidationError
from apps.vision.capture.hub import CaptureError, FrameMeta, hub
from apps.vision.sources.grabbers import Grabber
from vscapture.protocol import ENCODING_CODES, Encoding

MODES = ("on_demand", "stream")
log = logging.getLogger(__name__)


class CaptureGrabber(Grabber):
    kind = "capture"
    label = "Capture client camera"
    description = "The capture client program on the camera's PC acquires the image and sends it to the platform; on the same machine it uses shared memory automatically."
    fields = ["client", "channel", "mode", "timeout_ms", "fresh", "encoding"]

    def __init__(self, config: dict[str, Any], **kw: Any) -> None:
        super().__init__(config, **kw)
        self.client = str(config.get("client") or "").strip()
        self.channel = str(config.get("channel") or "").strip()
        if not self.client or not self.channel:
            raise ValidationError("Choose a capture client and a camera channel", code="capture_config")
        self.mode = "stream" if str(config.get("mode") or "") == "stream" else "on_demand"
        from django.conf import settings

        default_ms = int(getattr(settings, "VISION", {}).get("CAPTURE_TIMEOUT_MS", 1000))
        try:
            ms = int(config.get("timeout_ms") or default_ms)
        except (TypeError, ValueError):
            ms = default_ms
        self.timeout = max(50, min(30000, ms)) / 1000.0
        self.fresh = bool(config.get("fresh", True))
        enc = str(config.get("encoding") or "auto")
        self.encoding = int(ENCODING_CODES.get(enc, Encoding.AUTO))
        self.last_seq = 0
        self.last_meta: FrameMeta | None = None
        self.timed_out = False
        self._stream_session_id = 0
        self._params_session_id = 0
        self._last_sent_params: dict[str, Any] = {}
        self._last_param_result: dict[str, Any] = {"ok": True, "applied": {}, "errors": {}, "message": ""}
        if self.mode == "stream":
            hub.acquire_stream(self.client, self.channel, self.name)
            session = hub.get(self.client)
            self._stream_session_id = int(getattr(session, "session_id", 0)) if session is not None else 0
        elif self.name:
            hub.note_user(self.client, self.channel, self.name, True)

    def grab(self) -> np.ndarray | None:
        return self._grab_with(fresh=self.fresh, timeout=self.timeout)

    def grab_fresh(self, timeout: float | None = None) -> np.ndarray | None:
        """讓取像工具明確要求打光或改參數之後的新影格。"""
        return self._grab_with(fresh=True, timeout=timeout or self.timeout)

    def _grab_with(self, *, fresh: bool, timeout: float) -> np.ndarray | None:
        self.timed_out = False
        session = hub.get(self.client)
        if session is None:
            self.last_error = f"The capture client '{self.client}' is not connected"
            return None
        try:
            if self.mode == "stream":
                if int(getattr(session, "session_id", 0)) != self._stream_session_id:
                    hub.release_stream(self.client, self.channel, self.name)
                    hub.acquire_stream(self.client, self.channel, self.name)
                    self._stream_session_id = int(getattr(session, "session_id", 0))
                    # 新連線的通道序號從頭算：舊的 last_seq 留著會讓 wait_for_seq 等一個永遠不會來的序號。
                    with self._lock:
                        self.last_seq = 0
                        self.last_meta = None
                    log.info("擷取端串流來源 %s 偵測到 session 重連，已重新要求串流", self.name or self.client)
                frame = session.latest(self.channel)
                if frame is None or (fresh and frame.meta.seq <= self.last_seq):
                    frame = session.wait_for_seq(self.channel, self.last_seq if fresh else 0, timeout)
            else:
                min_seq = self.last_seq if fresh else 0
                frame = session.request_frame(self.channel, timeout=timeout, min_seq=min_seq, after_request=fresh, encoding=self.encoding)
        except CaptureError as exc:
            self.last_error = str(exc)
            self.timed_out = exc.code == "timeout"
            return None
        with self._lock:
            self.frames += 1
            self.last_seq = frame.meta.seq
            self.last_meta = frame.meta
            self.last_error = ""
            self.timed_out = False
        return frame.image

    def accept_frame(self, frame) -> np.ndarray:
        """stereo_grab 已經由 hub 取得 Frame 時，同步更新此 grabber 的狀態。"""
        with self._lock:
            self.frames += 1
            self.last_seq = frame.meta.seq
            self.last_meta = frame.meta
            self.last_error = ""
            self.timed_out = False
        return frame.image

    def _session_id(self) -> int:
        session = hub.get(self.client)
        return int(getattr(session, "session_id", 0)) if session is not None else 0

    def set_params_once(self, params: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        clean = {str(k): v for k, v in (params or {}).items() if str(k)}
        if not clean:
            return {"ok": True, "applied": {}, "errors": {}, "message": ""}
        session_id = self._session_id()
        if session_id and session_id == self._params_session_id and clean == self._last_sent_params:
            return dict(self._last_param_result)
        result = hub.set_channel_params(self.client, self.channel, clean, timeout or self.timeout)
        self._params_session_id = session_id
        self._last_sent_params = dict(clean)
        self._last_param_result = dict(result)
        return result

    def command(self, command: str, args: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        return hub.channel_command(self.client, self.channel, command, args or {}, timeout or self.timeout)

    def close(self) -> None:
        if self.mode == "stream":
            hub.release_stream(self.client, self.channel, self.name)
            self._stream_session_id = 0
        elif self.name:
            hub.note_user(self.client, self.channel, self.name, False)

    def info(self) -> dict[str, Any]:
        base = super().info()
        out: dict[str, Any] = {
            **base, "client": self.client, "channel": self.channel, "mode": self.mode, "fresh": self.fresh, "seq": self.last_seq, "latency_ms": None,
            **channel_status(self.client, self.channel, encoding=str(self.config.get("encoding") or "auto")),
        }
        if self.last_error:
            out["last_error"] = self.last_error
        if self.last_seq:
            out["seq"] = max(int(out.get("seq") or 0), self.last_seq)
        if self.last_meta is not None:
            out["latency_ms"] = round(self.last_meta.latency_ms, 2)
            out["width"], out["height"] = self.last_meta.width, self.last_meta.height
        return out


def channel_status(client: str, channel: str, *, encoding: str = "auto") -> dict[str, Any]:
    """擷取端某通道目前的狀態（不需要開啟來源）：connected／shm／seq／age_ms／fps／尺寸／串流；離線時只有 connected=False。"""
    session = hub.get(client)
    out: dict[str, Any] = {
        "connected": session is not None, "encoding": encoding, "shm": False, "seq": 0, "age_ms": None, "fps": 0.0,
        "width": None, "height": None, "roi": None, "full": None, "streaming": False, "last_error": "",
    }
    if session is None:
        return out
    try:
        ch = session.channel(channel)
    except CaptureError as exc:
        out["last_error"] = str(exc)
        return out
    d = ch.to_dict()
    out.update({
        "shm": session.shm is not None, "seq": d["seq"], "age_ms": d["last_frame_age_ms"], "fps": d["fps"], "encoding": d["encoding"] or encoding,
        "width": d["width"], "height": d["height"], "roi": d["roi"], "full": d["full"], "streaming": d["streaming"], "local": session.local, "last_error": d["last_error"],
    })
    return out


def capture_grabber_for_source(source_id: str | int) -> tuple[CaptureGrabber | None, str]:
    from apps.vision import sources

    key = str(source_id)
    try:
        sid = int(key)
    except (TypeError, ValueError):
        return None, "missing"
    with sources._lock:  # noqa: SLF001 - 相機控制要沿用來源快取，避免重開擷取來源。
        cached = sources._open.get(sid)  # noqa: SLF001
    if cached is not None:
        grabber = cached[1]
        return (grabber, "") if isinstance(grabber, CaptureGrabber) else (None, "not_capture")
    try:
        from apps.vision.models import ImageSource

        source = ImageSource.objects.get(pk=sid)
    except Exception:  # noqa: BLE001
        return None, "missing"
    if source.kind != CaptureGrabber.kind:
        return None, "not_capture"
    try:
        grabber = sources.open_source(source)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    return (grabber, "") if isinstance(grabber, CaptureGrabber) else (None, "not_capture")
