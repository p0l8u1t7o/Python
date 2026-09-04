"""IDS 舊款 uEye 相機（pyueye）。選配：多數新專案用 IDS peak（ids.py）；此後端只做基本自由取像與曝光／增益。"""

from __future__ import annotations

from ctypes import c_double
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec

try:
    from pyueye import ueye  # type: ignore

    _IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001
    ueye = None
    _IMPORT_ERROR = str(exc)


class UeyeCamera(Camera):
    backend = "ueye"
    label = "IDS uEye（舊款）"

    def __init__(self) -> None:
        self.h: Any = None
        self.mem: Any = None
        self.mem_id: Any = None
        self._w = self._h = 0
        self._pitch = 0
        self._mono = False
        self._running = False
        self._serial = ""

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return (True, "") if ueye is not None else (False, f"尚未安裝 pyueye／uEye 驅動（{_IMPORT_ERROR}）")

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        if ueye is None:
            return []
        n = ueye.INT()
        if ueye.is_GetNumberOfCameras(n) != ueye.IS_SUCCESS or n.value <= 0:
            return []
        lst = ueye.UEYE_CAMERA_LIST(ueye.UEYE_CAMERA_INFO * n.value)
        lst.dwCount = n.value
        ueye.is_GetCameraList(lst)
        return [DeviceInfo("ueye", f"id:{info.dwCameraID}", f"{info.Model.decode(errors='ignore')} #{info.dwCameraID}", model=info.Model.decode(errors="ignore"), serial=info.SerNo.decode(errors="ignore")) for info in lst.uci]

    def open(self, device_id: str) -> DeviceDescription:
        if ueye is None:
            raise CameraError(f"尚未安裝 pyueye（{_IMPORT_ERROR}）")
        cam_id = int(str(device_id).split(":")[-1])
        h = ueye.HIDS(cam_id)
        if ueye.is_InitCamera(h, None) != ueye.IS_SUCCESS:
            raise CameraError(f"無法開啟 uEye 相機 {cam_id}")
        self.h = h
        info = ueye.SENSORINFO()
        ueye.is_GetSensorInfo(h, info)
        self._w, self._h = int(info.nMaxWidth), int(info.nMaxHeight)
        self._mono = int(info.nColorMode) == ueye.IS_COLORMODE_MONOCHROME
        ueye.is_SetColorMode(h, ueye.IS_CM_MONO8 if self._mono else ueye.IS_CM_BGR8_PACKED)
        bits = 8 if self._mono else 24
        self.mem, self.mem_id = ueye.c_mem_p(), ueye.int()
        ueye.is_AllocImageMem(h, self._w, self._h, bits, self.mem, self.mem_id)
        ueye.is_SetImageMem(h, self.mem, self.mem_id)
        pitch = ueye.INT()
        ueye.is_InquireImageMem(h, self.mem, self.mem_id, ueye.INT(), ueye.INT(), ueye.INT(), pitch)
        self._pitch = int(pitch)
        self._serial = info.strSensorName.decode(errors="ignore")
        return self.describe()

    def close(self) -> None:
        if self.h is not None:
            if self.mem is not None:
                ueye.is_FreeImageMem(self.h, self.mem, self.mem_id)
            ueye.is_ExitCamera(self.h)
        self.h = None
        self._running = False

    def start(self) -> None:
        if self.h is None:
            raise CameraError("相機尚未開啟")
        ueye.is_CaptureVideo(self.h, ueye.IS_DONT_WAIT)
        self._running = True

    def stop(self) -> None:
        if self.h is not None and self._running:
            ueye.is_StopLiveVideo(self.h, ueye.IS_FORCE_VIDEO_STOP)
        self._running = False

    @property
    def is_open(self) -> bool:
        return self.h is not None

    @property
    def is_running(self) -> bool:
        return self._running

    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        if not self._running:
            return None
        bits = 8 if self._mono else 24
        data = ueye.get_data(self.mem, self._w, self._h, bits, self._pitch, copy=True)
        arr = np.reshape(data, (self._h, self._pitch // (bits // 8), 1 if self._mono else 3))[:, : self._w]
        return (arr[:, :, 0] if self._mono else arr).copy(), (0, 0)

    def get_params(self) -> dict[str, ParamSpec]:
        if self.h is None:
            return {}
        exp = c_double()
        ueye.is_Exposure(self.h, ueye.IS_EXPOSURE_CMD_GET_EXPOSURE, exp, 8)
        return {
            "exposure_us": ParamSpec("exposure_us", "float", exp.value * 1000.0, 10.0, 1e6, None, unit="µs", standard=True, label="曝光時間"),
            "gain_db": ParamSpec("gain_db", "float", float(ueye.is_SetHardwareGain(self.h, ueye.IS_GET_MASTER_GAIN, ueye.IS_IGNORE_PARAMETER, ueye.IS_IGNORE_PARAMETER, ueye.IS_IGNORE_PARAMETER)), 0.0, 100.0, 1.0, standard=True, label="增益（0～100）"),
            "pixel_format": ParamSpec("pixel_format", "enum", "Mono8" if self._mono else "BGR8", choices=["Mono8" if self._mono else "BGR8"], standard=True, label="像素格式", writable=False),
            "trigger_mode": ParamSpec("trigger_mode", "enum", "freerun", choices=["freerun"], standard=True, label="觸發模式", writable=False),
        }

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.h is None:
            raise CameraError("相機尚未開啟")
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, value in values.items():
            try:
                if key == "exposure_us":
                    ms = c_double(float(value) / 1000.0)
                    ueye.is_Exposure(self.h, ueye.IS_EXPOSURE_CMD_SET_EXPOSURE, ms, 8)
                    applied[key] = ms.value * 1000.0
                elif key == "gain_db":
                    ueye.is_SetHardwareGain(self.h, int(value), ueye.IS_IGNORE_PARAMETER, ueye.IS_IGNORE_PARAMETER, ueye.IS_IGNORE_PARAMETER)
                    applied[key] = int(value)
                elif key in ("pixel_format", "trigger_mode", "fps", "width", "height", "offset_x", "offset_y"):
                    applied[key] = value
                else:
                    errors[key] = "不支援的參數"
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
        if errors:
            raise CameraParamError(errors)
        return applied

    def describe(self) -> DeviceDescription:
        return DeviceDescription("ueye", "uEye", self._serial, self._w, self._h, ["Mono8" if self._mono else "BGR8"], False, False, False, not self._mono)
