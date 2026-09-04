"""影像來源「擷取端相機」：向 hub 要一張（依需求）或取串流最新影格。"""

from __future__ import annotations

from typing import Any

import numpy as np

from apps.core.errors import ValidationError
from apps.vision.capture.hub import CaptureError, FrameMeta, hub
from apps.vision.sources.grabbers import Grabber
from vscapture.protocol import ENCODING_CODES, Encoding

MODES = ("on_demand", "stream")


class CaptureGrabber(Grabber):
    kind = "capture"
    label = "擷取端相機"
    description = "由安裝在相機電腦上的「擷取端」程式取像並送到平台；同機自動走共享記憶體。"
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
        if self.mode == "stream":
            hub.acquire_stream(self.client, self.channel, self.name)
        elif self.name:
            hub.note_user(self.client, self.channel, self.name, True)

    def grab(self) -> np.ndarray | None:
        session = hub.get(self.client)
        if session is None:
            self.last_error = f"擷取端「{self.client}」未連線"
            return None
        try:
            if self.mode == "stream":
                frame = session.latest(self.channel)
                if frame is None or (self.fresh and frame.meta.seq <= self.last_seq):
                    frame = session.wait_for_seq(self.channel, self.last_seq if self.fresh else 0, self.timeout)
            else:
                min_seq = self.last_seq if self.fresh else 0
                frame = session.request_frame(self.channel, timeout=self.timeout, min_seq=min_seq, after_request=self.fresh, encoding=self.encoding)
        except CaptureError as exc:
            self.last_error = str(exc)
            return None
        with self._lock:
            self.frames += 1
            self.last_seq = frame.meta.seq
            self.last_meta = frame.meta
            self.last_error = ""
        return frame.image

    def close(self) -> None:
        if self.mode == "stream":
            hub.release_stream(self.client, self.channel, self.name)
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
