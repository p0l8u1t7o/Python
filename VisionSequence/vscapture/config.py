"""擷取端設定：`%APPDATA%/VisionSequenceCapture/config.json`（env `VSCAPTURE_CONFIG` 覆寫）。

缺鍵補預設、未知鍵忽略、非法值拋 ConfigError（帶欄位路徑）；寫檔先寫 .tmp 再 os.replace（原子）。
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Iterable

APP_DIR_NAME = "VisionSequenceCapture"
BACKEND_NAMES = ("webcam", "basler", "ids", "ueye", "fake")
ENCODINGS = ("raw", "lz4", "jpeg")
MODES = ("on_demand", "stream")
TRIGGER_MODES = ("freerun", "software", "hardware")
LOCAL_MODES = ("auto", "force", "off")


class ConfigError(ValueError):
    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(f"{path}：{message}" if path else message)
        self.path = path


def app_dir() -> Path:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
    return Path(base or os.path.expanduser("~")) / APP_DIR_NAME


def default_config_path() -> Path:
    override = os.environ.get("VSCAPTURE_CONFIG")
    return Path(override) if override else app_dir() / "config.json"


def _pick(d: dict[str, Any], key: str, default: Any, path: str, kind: type | tuple[type, ...], choices: Iterable[str] | None = None) -> Any:
    v = d.get(key, default)
    if v is None:
        return default if default is not None else None
    if kind is float and isinstance(v, bool):
        raise ConfigError("必須是數值", f"{path}.{key}")
    if kind is float and isinstance(v, int):
        v = float(v)
    if not isinstance(v, kind):
        raise ConfigError(f"型別錯誤（應為 {getattr(kind, '__name__', kind)}）", f"{path}.{key}")
    if choices is not None and v not in tuple(choices):
        raise ConfigError(f"只能是 {'、'.join(choices)}", f"{path}.{key}")
    return v


@dataclass
class ConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 9100
    client_name: str = field(default_factory=lambda: (socket.gethostname() or "capture")[:64])
    api_key: str = ""
    auto_connect: bool = True
    local_mode: str = "auto"  # auto | force | off
    heartbeat_s: float = 2.0
    reconnect_max_s: float = 30.0

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str = "connection") -> ConnectionConfig:
        base = cls()
        return cls(
            host=_pick(d, "host", base.host, path, str) or base.host,
            port=int(_pick(d, "port", base.port, path, int)),
            client_name=str(_pick(d, "client_name", base.client_name, path, str) or base.client_name)[:64],
            api_key=str(_pick(d, "api_key", "", path, str)),
            auto_connect=bool(_pick(d, "auto_connect", True, path, bool)),
            local_mode=_pick(d, "local_mode", "auto", path, str, LOCAL_MODES),
            heartbeat_s=float(_pick(d, "heartbeat_s", 2.0, path, float)),
            reconnect_max_s=float(_pick(d, "reconnect_max_s", 30.0, path, float)),
        )


@dataclass
class CameraParams:
    exposure_us: float | None = None
    gain_db: float | None = None
    fps: float | None = None
    pixel_format: str | None = None
    width: int | None = None
    height: int | None = None
    offset_x: int = 0
    offset_y: int = 0
    trigger_mode: str = "freerun"

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str) -> CameraParams:
        def opt(key: str, kind: type) -> Any:
            v = d.get(key)
            if v is None or v == "":
                return None
            if kind is float and isinstance(v, int) and not isinstance(v, bool):
                v = float(v)
            if not isinstance(v, kind) or isinstance(v, bool):
                raise ConfigError(f"型別錯誤（應為 {kind.__name__}）", f"{path}.{key}")
            return v

        return cls(
            exposure_us=opt("exposure_us", float), gain_db=opt("gain_db", float), fps=opt("fps", float),
            pixel_format=opt("pixel_format", str), width=opt("width", int), height=opt("height", int),
            offset_x=int(d.get("offset_x") or 0), offset_y=int(d.get("offset_y") or 0),
            trigger_mode=_pick(d, "trigger_mode", "freerun", path, str, TRIGGER_MODES),
        )

    def to_values(self) -> dict[str, Any]:
        """只回有設定的值（給 camera.set_params）。"""
        return {k: v for k, v in asdict(self).items() if v is not None and not (k in ("offset_x", "offset_y") and v == 0)}


@dataclass
class Roi:
    x: int = 0
    y: int = 0
    w: int = 0  # 0 = 全幅
    h: int = 0

    def is_full(self) -> bool:
        return self.w <= 0 or self.h <= 0

    def clamp(self, sensor_w: int, sensor_h: int) -> Roi:
        if self.is_full() or sensor_w <= 0 or sensor_h <= 0:
            return Roi()
        x = max(0, min(self.x, sensor_w - 1))
        y = max(0, min(self.y, sensor_h - 1))
        w = max(1, min(self.w, sensor_w - x))
        h = max(1, min(self.h, sensor_h - y))
        if w == sensor_w and h == sensor_h and x == 0 and y == 0:
            return Roi()
        return Roi(x, y, w, h)

    @classmethod
    def from_dict(cls, d: Any, path: str) -> Roi:
        if not d:
            return cls()
        if not isinstance(d, dict):
            raise ConfigError("必須是 {x, y, w, h}", path)
        try:
            return cls(int(d.get("x", 0) or 0), int(d.get("y", 0) or 0), int(d.get("w", 0) or 0), int(d.get("h", 0) or 0))
        except (TypeError, ValueError):
            raise ConfigError("x/y/w/h 必須是整數", path) from None


@dataclass
class DeliveryConfig:
    encoding: str = "lz4"  # raw | lz4 | jpeg
    jpeg_quality: int = 90
    mono: bool = False
    downscale: int = 1  # 1 | 2 | 4
    mode: str = "on_demand"  # on_demand | stream
    stream_fps: float = 10.0

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str) -> DeliveryConfig:
        return cls(
            encoding=_pick(d, "encoding", "lz4", path, str, ENCODINGS),
            jpeg_quality=max(1, min(100, int(_pick(d, "jpeg_quality", 90, path, int)))),
            mono=bool(_pick(d, "mono", False, path, bool)),
            downscale=int(_pick(d, "downscale", 1, path, int, (1, 2, 4))),
            mode=_pick(d, "mode", "on_demand", path, str, MODES),
            stream_fps=float(_pick(d, "stream_fps", 10.0, path, float)),
        )


@dataclass
class ChannelConfig:
    id: str
    name: str = ""
    enabled: bool = True
    preview: bool = True
    backend: str = "webcam"
    device_id: str = ""
    params: CameraParams = field(default_factory=CameraParams)
    extras: dict[str, Any] = field(default_factory=dict)
    roi: Roi = field(default_factory=Roi)
    hw_roi: bool = False
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str) -> ChannelConfig:
        cid = str(d.get("id") or "").strip()
        if not cid:
            raise ConfigError("缺少 id", path)
        return cls(
            id=cid, name=str(d.get("name") or cid), enabled=bool(_pick(d, "enabled", True, path, bool)), preview=bool(_pick(d, "preview", True, path, bool)),
            backend=_pick(d, "backend", "webcam", path, str, BACKEND_NAMES), device_id=str(d.get("device_id") or ""),
            params=CameraParams.from_dict(d.get("params") or {}, f"{path}.params"),
            extras=dict(d.get("extras") or {}), roi=Roi.from_dict(d.get("roi"), f"{path}.roi"), hw_roi=bool(_pick(d, "hw_roi", False, path, bool)),
            delivery=DeliveryConfig.from_dict(d.get("delivery") or {}, f"{path}.delivery"),
        )


@dataclass
class UiConfig:
    start_minimized: bool = False
    preview_fps: int = 15
    window_geometry: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any], path: str = "ui") -> UiConfig:
        return cls(bool(_pick(d, "start_minimized", False, path, bool)), max(1, min(60, int(_pick(d, "preview_fps", 15, path, int)))), str(d.get("window_geometry") or ""))


@dataclass
class AppConfig:
    version: int = 1
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    log_level: str = "INFO"
    channels: list[ChannelConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppConfig:
        if not isinstance(d, dict):
            raise ConfigError("設定檔必須是 JSON 物件")
        channels = [ChannelConfig.from_dict(c, f"channels[{i}]") for i, c in enumerate(d.get("channels") or [])]
        seen: set[str] = set()
        for c in channels:
            if c.id in seen:
                raise ConfigError(f"通道 id 重複：{c.id}", "channels")
            seen.add(c.id)
        return cls(
            version=int(d.get("version") or 1), connection=ConnectionConfig.from_dict(d.get("connection") or {}),
            ui=UiConfig.from_dict(d.get("ui") or {}), log_level=str(d.get("log_level") or "INFO").upper(), channels=channels,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def channel(self, cid: str) -> ChannelConfig | None:
        return next((c for c in self.channels if c.id == cid), None)


def load(path: Path | None = None) -> AppConfig:
    p = path or default_config_path()
    if not p.is_file():
        return AppConfig()
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"設定檔無法讀取：{exc}") from None
    return AppConfig.from_dict(raw)


def save(cfg: AppConfig, path: Path | None = None) -> Path:
    p = path or default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def new_channel_id(existing: Iterable[str]) -> str:
    used = set(existing)
    n = 1
    while f"cam{n}" in used:
        n += 1
    return f"cam{n}"


def field_names(cls: type) -> list[str]:
    return [f.name for f in fields(cls)]
