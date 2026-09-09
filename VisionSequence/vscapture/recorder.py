"""擷取端本機錄影：每通道一條寫檔執行緒，從 FrameSlot 取最新影格。

錄影只讀最新影格，不排命令到相機執行緒，也不進傳送佇列；寫檔跟不上時以 seq 落差計入 dropped，
直接跳到最新影格，避免阻塞取像與伺服端 GRAB。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any

import cv2
import numpy as np

from vscapture.config import app_dir
from vscapture.frames import Frame

log = logging.getLogger(__name__)

CODECS = ("MJPG", "H264", "HEVC")
SCALES = (1.0, 0.5, 0.25)


def default_recording_dir() -> Path:
    """預設錄影資料夾，位於擷取端設定資料夾底下。"""
    return app_dir() / "recordings"


@dataclass
class RecordConfig:
    folder: str = ""
    codec: str = "MJPG"
    fps_divisor: int = 1
    scale: float = 1.0
    max_minutes: float = 0.0
    server_folder: str = ""
    auto_upload: bool = False

    def normalized(self) -> RecordConfig:
        codec = str(self.codec or "MJPG").upper()
        if codec not in CODECS:
            codec = "MJPG"
        scale = min(SCALES, key=lambda item: abs(float(self.scale or 1.0) - item))
        return RecordConfig(
            folder=str(self.folder or default_recording_dir()),
            codec=codec,
            fps_divisor=max(1, int(self.fps_divisor or 1)),
            scale=float(scale),
            max_minutes=max(0.0, float(self.max_minutes or 0.0)),
            server_folder=str(self.server_folder or ""),
            auto_upload=bool(self.auto_upload),
        )


@dataclass
class RecordingStatus:
    channel: str
    active: bool = False
    path: str = ""
    codec: str = ""
    requested_codec: str = ""
    fallback_reason: str = ""
    started_at: float = 0.0
    duration_s: float = 0.0
    bytes: int = 0
    frames: int = 0
    dropped: int = 0
    skipped: int = 0
    actual_fps: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel, "active": self.active, "path": self.path, "codec": self.codec,
            "requested_codec": self.requested_codec, "fallback_reason": self.fallback_reason,
            "started_at": self.started_at, "duration_s": round(self.duration_s, 1), "bytes": self.bytes,
            "frames": self.frames, "dropped": self.dropped, "skipped": self.skipped,
            "actual_fps": round(self.actual_fps, 2), "error": self.error,
        }


class Recorder:
    """單一通道的錄影器。呼叫端提供 `latest()`，本類別只讀取最新影格並寫檔。"""

    def __init__(self, channel_id: str, latest, cfg: RecordConfig, *, nominal_fps: float = 30.0) -> None:
        self.channel_id = channel_id
        self.latest = latest
        self.cfg = cfg.normalized()
        self.nominal_fps = max(1.0, float(nominal_fps or 30.0))
        self.stop_event = Event()
        self.thread: Thread | None = None
        self.status = RecordingStatus(channel=channel_id, requested_codec=self.cfg.codec)
        self._writer: cv2.VideoWriter | None = None
        self._last_seq = 0
        self._last_write_perf = 0.0
        self._fps_window_start = 0.0
        self._fps_window_frames = 0

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self._run, name=f"vsc-rec-{self.channel_id}", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            self.thread = None

    def _run(self) -> None:
        self.status.active = True
        self.status.started_at = time.time()
        self._fps_window_start = time.perf_counter()
        try:
            folder = Path(self.cfg.server_folder or self.cfg.folder)
            folder.mkdir(parents=True, exist_ok=True)
            deadline = time.perf_counter() + self.cfg.max_minutes * 60.0 if self.cfg.max_minutes > 0 else 0.0
            while not self.stop_event.is_set():
                if deadline and time.perf_counter() >= deadline:
                    break
                frame = self.latest()
                if frame is None or frame.seq == self._last_seq:
                    time.sleep(0.002)
                    continue
                self._handle_frame(frame, folder)
        except Exception as exc:  # noqa: BLE001
            self.status.error = str(exc)
            log.warning("錄影 %s 失敗：%s", self.channel_id, exc)
        finally:
            writer, self._writer = self._writer, None
            if writer is not None:
                writer.release()
            self.status.active = False
            self._update_size()
            self._update_duration()

    def _handle_frame(self, frame: Frame, folder: Path) -> None:
        gap = max(0, frame.seq - self._last_seq - 1) if self._last_seq else 0
        if gap:
            self.status.dropped += gap // self.cfg.fps_divisor
        if frame.seq % self.cfg.fps_divisor:
            self.status.skipped += 1
            self._last_seq = frame.seq
            return
        arr = self._prepare(frame.image)
        if self._writer is None:
            self._open_writer(folder, arr)
        writer = self._writer
        if writer is None:
            self.status.dropped += 1
            self._last_seq = frame.seq
            return
        writer.write(arr)
        self.status.frames += 1
        self._last_seq = frame.seq
        self._last_write_perf = time.perf_counter()
        self._fps_window_frames += 1
        self._refresh_status()

    def _prepare(self, image: np.ndarray) -> np.ndarray:
        arr = image
        if arr.dtype != np.uint8:
            arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        if self.cfg.scale != 1.0:
            h, w = arr.shape[:2]
            arr = cv2.resize(arr, (max(1, int(w * self.cfg.scale)), max(1, int(h * self.cfg.scale))), interpolation=cv2.INTER_AREA)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        return np.ascontiguousarray(arr)

    def _open_writer(self, folder: Path, arr: np.ndarray) -> None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        fps = max(1.0, self.nominal_fps / self.cfg.fps_divisor)
        attempts = self._codec_attempts(self.cfg.codec)
        reasons: list[str] = []
        for codec, ext, fourcc_name in attempts:
            path = folder / f"{self.channel_id}_{stamp}{ext}"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc_name), fps, (arr.shape[1], arr.shape[0]))
            if writer.isOpened():
                self._writer = writer
                self.status.path = str(path)
                self.status.codec = codec
                self.status.fallback_reason = "; ".join(reasons)
                return
            reasons.append(f"{codec}/{fourcc_name} unavailable")
            writer.release()
        raise RuntimeError("; ".join(reasons) or "Could not open the video writer")

    @staticmethod
    def _codec_attempts(codec: str) -> list[tuple[str, str, str]]:
        if codec == "H264":
            return [("H264", ".mp4", "H264"), ("H264", ".mp4", "avc1"), ("MJPG", ".avi", "MJPG")]
        if codec == "HEVC":
            return [("HEVC", ".mp4", "HEVC"), ("HEVC", ".mp4", "hvc1"), ("HEVC", ".mp4", "H265"), ("MJPG", ".avi", "MJPG")]
        return [("MJPG", ".avi", "MJPG")]

    def _refresh_status(self) -> None:
        now = time.perf_counter()
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self.status.actual_fps = self._fps_window_frames / elapsed
            self._fps_window_start = now
            self._fps_window_frames = 0
        self._update_duration()
        self._update_size()

    def _update_duration(self) -> None:
        if self.status.started_at:
            self.status.duration_s = max(0.0, time.time() - self.status.started_at)

    def _update_size(self) -> None:
        if self.status.path:
            try:
                self.status.bytes = Path(self.status.path).stat().st_size
            except OSError:
                pass
