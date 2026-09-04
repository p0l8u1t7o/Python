"""相機後端共用介面：所有 SDK 物件只在通道的擷取執行緒使用（Channel.call 把命令送過去執行）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vscapture.config import Roi

STANDARD_PARAMS = ("exposure_us", "gain_db", "fps", "pixel_format", "width", "height", "offset_x", "offset_y", "trigger_mode")


class CameraError(Exception):
    """相機操作失敗（開啟／取像／參數）。"""


class SdkMissing(CameraError):
    """該種相機的 SDK 尚未安裝。"""


class CameraParamError(CameraError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("；".join(f"{k}：{v}" for k, v in errors.items()) or "參數設定失敗")
        self.errors = errors


@dataclass
class DeviceInfo:
    backend: str
    device_id: str
    label: str
    model: str = ""
    serial: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceDescription:
    backend: str
    model: str = ""
    serial: str = ""
    sensor_w: int = 0
    sensor_h: int = 0
    pixel_formats: list[str] = field(default_factory=list)
    supports_hw_roi: bool = False
    supports_hw_trigger: bool = False
    supports_sw_trigger: bool = False
    native_color: bool = True


@dataclass
class ParamSpec:
    name: str
    kind: str  # int | float | bool | enum | str | command
    value: Any = None
    min: Any = None
    max: Any = None
    step: Any = None
    choices: list[str] = field(default_factory=list)
    unit: str = ""
    writable: bool = True
    standard: bool = False
    group: str = ""
    label: str = ""


class Camera(ABC):
    """一台相機。所有方法只在擷取執行緒呼叫；回傳的影像陣列由相機每次新配置，發布後不再改動。"""

    backend: str = ""
    label: str = ""

    @classmethod
    def available(cls) -> tuple[bool, str]:
        """(SDK 是否可用, 原因)。"""
        return True, ""

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        return []

    @abstractmethod
    def open(self, device_id: str) -> DeviceDescription: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        """取一張（自由取像／硬體觸發模式）；逾時回 None。回 (影像, 硬體 ROI 左上角)。"""

    def snap(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]]:
        """軟體觸發：觸發並等一張；不支援觸發的相機＝下一張新影格。"""
        got = self.grab_one(timeout)
        if got is None:
            raise CameraError("擷取逾時")
        return got

    @abstractmethod
    def get_params(self) -> dict[str, ParamSpec]: ...

    @abstractmethod
    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        """套用參數，回實際生效值；個別失敗收集進 CameraParamError.errors（其餘仍套用）。"""

    def apply_roi(self, roi: Roi, hardware: bool) -> tuple[bool, Roi]:
        """回 (是否硬體 ROI, 實際生效的 ROI)。預設不支援硬體 ROI → 軟體裁切。"""
        return False, roi

    @abstractmethod
    def describe(self) -> DeviceDescription: ...

    @property
    def is_open(self) -> bool:
        return False

    @property
    def is_running(self) -> bool:
        return False

    @property
    def trigger_mode(self) -> str:
        return "freerun"


def align(value: int, minimum: int, maximum: int, inc: int) -> int:
    """把整數對齊到 [minimum, maximum] 且符合增量。"""
    inc = max(1, int(inc))
    v = max(int(minimum), min(int(maximum), int(value)))
    return minimum + ((v - minimum) // inc) * inc
