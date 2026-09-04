"""Basler 相機（pypylon）。裝置以序號指定（`serial:<sn>`）；支援硬體 ROI、軟體／硬體觸發、GenICam 進階節點。

需要 pylon Runtime（GigE 過濾驅動、USB3 驅動）；`PYLON_CAMEMU=1` 可在沒有相機的機器出現模擬相機。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec, align
from vscapture.config import Roi

log = logging.getLogger(__name__)

try:
    from pypylon import genicam, pylon  # type: ignore

    _IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001 — ImportError 或 pylon 執行期缺件
    pylon = None
    genicam = None
    _IMPORT_ERROR = str(exc)

EXTRA_NODES = ("ExposureAuto", "GainAuto", "BalanceWhiteAuto", "Gamma", "BlackLevel", "ReverseX", "ReverseY", "BinningHorizontal", "BinningVertical",
               "TriggerDelay", "LineSelector", "LineMode", "GevSCPSPacketSize", "DeviceLinkThroughputLimit", "AcquisitionFrameRateEnable")


class BaslerCamera(Camera):
    backend = "basler"
    label = "Basler（pylon）"

    def __init__(self) -> None:
        self.cam: Any = None
        self.converter: Any = None
        self._serial = ""
        self._model = ""
        self._mono = True
        self._trigger = "freerun"
        self._grabbing = False

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return (True, "") if pylon is not None else (False, f"尚未安裝 pypylon／pylon Runtime（{_IMPORT_ERROR}）")

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        if pylon is None:
            return []
        out: list[DeviceInfo] = []
        for di in pylon.TlFactory.GetInstance().EnumerateDevices():
            extra = {"class": di.GetDeviceClass()}
            if hasattr(di, "GetIpAddress") and di.GetDeviceClass() == "BaslerGigE":
                try:
                    extra["ip"] = di.GetIpAddress()
                except Exception:  # noqa: BLE001
                    pass
            out.append(DeviceInfo("basler", f"serial:{di.GetSerialNumber()}", di.GetFriendlyName(), model=di.GetModelName(), serial=di.GetSerialNumber(), extra=extra))
        return out

    # ---- 節點小工具 ----
    def _node(self, name: str) -> Any:
        try:
            node = getattr(self.cam, name)
        except (AttributeError, genicam.LogicalErrorException):
            return None
        return node if genicam.IsAvailable(node) else None

    def _get(self, name: str, default: Any = None) -> Any:
        node = self._node(name)
        if node is None:
            return default
        try:
            return node.GetValue()
        except Exception:  # noqa: BLE001
            return default

    def _set(self, name: str, value: Any) -> Any:
        node = self._node(name)
        if node is None or not genicam.IsWritable(node):
            raise ValueError(f"{name} 無法設定")
        node.SetValue(value)
        return node.GetValue()

    def open(self, device_id: str) -> DeviceDescription:
        if pylon is None:
            raise CameraError(f"尚未安裝 pypylon（{_IMPORT_ERROR}）")
        serial = str(device_id).split(":")[-1]
        tlf = pylon.TlFactory.GetInstance()
        info = pylon.DeviceInfo()
        info.SetSerialNumber(serial)
        devices = tlf.EnumerateDevices([info])
        if not devices:
            raise CameraError(f"找不到序號 {serial} 的 Basler 相機")
        cam = pylon.InstantCamera(tlf.CreateDevice(devices[0]))
        cam.Open()
        cam.MaxNumBuffer = 5
        self.cam = cam
        self._serial, self._model = serial, devices[0].GetModelName()
        self._refresh_converter()
        return self.describe()

    def _refresh_converter(self) -> None:
        fmt = str(self._get("PixelFormat", "Mono8"))
        self._mono = fmt.startswith("Mono") or fmt.startswith("Bayer") and False
        conv = pylon.ImageFormatConverter()
        conv.OutputPixelFormat = pylon.PixelType_Mono8 if fmt.startswith("Mono") else pylon.PixelType_BGR8packed
        conv.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
        self.converter = conv
        self._mono = fmt.startswith("Mono")

    def close(self) -> None:
        cam, self.cam = self.cam, None
        if cam is not None:
            try:
                if cam.IsGrabbing():
                    cam.StopGrabbing()
            finally:
                cam.Close()
        self._grabbing = False

    def start(self) -> None:
        if self.cam is None:
            raise CameraError("相機尚未開啟")
        if not self.cam.IsGrabbing():
            self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        self._grabbing = True

    def stop(self) -> None:
        if self.cam is not None and self.cam.IsGrabbing():
            self.cam.StopGrabbing()
        self._grabbing = False

    @property
    def is_open(self) -> bool:
        return self.cam is not None

    @property
    def is_running(self) -> bool:
        return self._grabbing

    @property
    def trigger_mode(self) -> str:
        return self._trigger

    def _convert(self, res: Any) -> np.ndarray:
        fmt = str(self._get("PixelFormat", "Mono8"))
        if fmt in ("Mono8", "BGR8"):
            return res.GetArray().copy()  # GetArray 是 view，Release 前要 copy
        return np.ascontiguousarray(self.converter.Convert(res).GetArray())

    def _origin(self) -> tuple[int, int]:
        return int(self._get("OffsetX", 0) or 0), int(self._get("OffsetY", 0) or 0)

    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        cam = self.cam
        if cam is None or not cam.IsGrabbing():
            return None
        res = cam.RetrieveResult(int(timeout * 1000), pylon.TimeoutHandling_Return)
        if res is None or not res.IsValid():
            return None
        try:
            if not res.GrabSucceeded():
                raise CameraError(f"取像失敗：{res.GetErrorDescription()}")
            return self._convert(res), self._origin()
        finally:
            res.Release()

    def snap(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]]:
        cam = self.cam
        if cam is None:
            raise CameraError("相機尚未開啟")
        if not cam.IsGrabbing():
            cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            self._grabbing = True
        if self._trigger == "software":
            cam.WaitForFrameTriggerReady(1000, pylon.TimeoutHandling_ThrowException)
            cam.ExecuteSoftwareTrigger()
        got = self.grab_one(timeout)
        if got is None:
            raise CameraError("擷取逾時")
        return got

    # ---- 參數 ----
    def _spec_from_node(self, name: str, *, standard: bool = False, label: str = "") -> ParamSpec | None:
        node = self._node(name)
        if node is None:
            return None
        writable = genicam.IsWritable(node)
        try:
            if isinstance(node, genicam.IEnumeration):
                return ParamSpec(name, "enum", str(node.GetValue()), choices=list(node.Symbolics), writable=writable, standard=standard, label=label or name, group="進階")
            if isinstance(node, genicam.IBoolean):
                return ParamSpec(name, "bool", bool(node.GetValue()), writable=writable, standard=standard, label=label or name, group="進階")
            if isinstance(node, genicam.IInteger):
                return ParamSpec(name, "int", int(node.GetValue()), int(node.GetMin()), int(node.GetMax()), int(node.GetInc()), writable=writable, standard=standard, label=label or name, group="進階")
            if isinstance(node, genicam.IFloat):
                return ParamSpec(name, "float", float(node.GetValue()), float(node.GetMin()), float(node.GetMax()), None, unit=str(node.GetUnit() or ""), writable=writable, standard=standard, label=label or name, group="進階")
            if isinstance(node, genicam.ICommand):
                return ParamSpec(name, "command", None, writable=writable, label=label or name, group="進階")
        except Exception:  # noqa: BLE001
            return None
        return None

    def get_params(self) -> dict[str, ParamSpec]:
        if self.cam is None:
            return {}
        out: dict[str, ParamSpec] = {}
        exp = self._spec_from_node("ExposureTime") or self._spec_from_node("ExposureTimeAbs") or self._spec_from_node("ExposureTimeRaw")
        if exp:
            out["exposure_us"] = ParamSpec("exposure_us", "float", float(exp.value), exp.min, exp.max, None, unit="µs", standard=True, label="曝光時間")
        gain = self._spec_from_node("Gain") or self._spec_from_node("GainRaw")
        if gain:
            out["gain_db"] = ParamSpec("gain_db", "float", float(gain.value), gain.min, gain.max, None, unit="dB" if gain.name == "Gain" else "raw", standard=True, label="增益")
        fps = self._spec_from_node("AcquisitionFrameRate") or self._spec_from_node("AcquisitionFrameRateAbs")
        if fps:
            out["fps"] = ParamSpec("fps", "float", float(fps.value), fps.min, fps.max, None, unit="fps", standard=True, label="影格率")
        pf = self._spec_from_node("PixelFormat")
        if pf:
            out["pixel_format"] = ParamSpec("pixel_format", "enum", pf.value, choices=pf.choices, standard=True, label="像素格式")
        for name, key, label in (("Width", "width", "寬"), ("Height", "height", "高"), ("OffsetX", "offset_x", "X 位移"), ("OffsetY", "offset_y", "Y 位移")):
            spec = self._spec_from_node(name)
            if spec:
                out[key] = ParamSpec(key, "int", spec.value, spec.min, spec.max, spec.step, standard=True, label=label)
        modes = ["freerun"]
        if self._node("TriggerMode") is not None:
            modes += ["software", "hardware"]
        out["trigger_mode"] = ParamSpec("trigger_mode", "enum", self._trigger, choices=modes, standard=True, label="觸發模式")
        for name in EXTRA_NODES:
            spec = self._spec_from_node(name)
            if spec:
                out[name] = spec
        return out

    def _set_roi_nodes(self, x: int, y: int, w: int, h: int) -> Roi:
        was = self.cam.IsGrabbing()
        if was:
            self.cam.StopGrabbing()
        try:
            self._set("OffsetX", 0)
            self._set("OffsetY", 0)
            wn, hn = self._node("Width"), self._node("Height")
            w = align(w, wn.GetMin(), wn.GetMax(), wn.GetInc())
            h = align(h, hn.GetMin(), hn.GetMax(), hn.GetInc())
            self._set("Width", w)
            self._set("Height", h)
            xn, yn = self._node("OffsetX"), self._node("OffsetY")
            x = align(x, xn.GetMin(), xn.GetMax(), xn.GetInc())
            y = align(y, yn.GetMin(), yn.GetMax(), yn.GetInc())
            self._set("OffsetX", x)
            self._set("OffsetY", y)
        finally:
            if was:
                self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        return Roi(x, y, w, h)

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.cam is None:
            raise CameraError("相機尚未開啟")
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        roi_keys = {k: v for k, v in values.items() if k in ("width", "height", "offset_x", "offset_y")}
        for key, value in values.items():
            if key in roi_keys:
                continue
            try:
                if key == "exposure_us":
                    name = next(n for n in ("ExposureTime", "ExposureTimeAbs", "ExposureTimeRaw") if self._node(n) is not None)
                    applied[key] = float(self._set(name, float(value) if name != "ExposureTimeRaw" else int(value)))
                elif key == "gain_db":
                    name = "Gain" if self._node("Gain") is not None else "GainRaw"
                    applied[key] = float(self._set(name, float(value) if name == "Gain" else int(value)))
                elif key == "fps":
                    if self._node("AcquisitionFrameRateEnable") is not None:
                        self._set("AcquisitionFrameRateEnable", True)
                    name = "AcquisitionFrameRate" if self._node("AcquisitionFrameRate") is not None else "AcquisitionFrameRateAbs"
                    applied[key] = float(self._set(name, float(value)))
                elif key == "pixel_format":
                    was = self.cam.IsGrabbing()
                    if was:
                        self.cam.StopGrabbing()
                    applied[key] = str(self._set("PixelFormat", str(value)))
                    self._refresh_converter()
                    if was:
                        self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                elif key == "trigger_mode":
                    mode = str(value)
                    if mode not in ("freerun", "software", "hardware"):
                        raise ValueError("觸發模式無效")
                    self._set("TriggerSelector", "FrameStart")
                    self._set("TriggerMode", "Off" if mode == "freerun" else "On")
                    if mode != "freerun":
                        self._set("TriggerSource", "Software" if mode == "software" else "Line1")
                    self._trigger = mode
                    applied[key] = mode
                else:
                    node = self._node(key)
                    if node is None:
                        raise ValueError("沒有此節點")
                    if isinstance(node, genicam.ICommand):
                        node.Execute()
                        applied[key] = None
                    elif isinstance(node, genicam.IEnumeration):
                        applied[key] = str(self._set(key, str(value)))
                    elif isinstance(node, genicam.IBoolean):
                        applied[key] = bool(self._set(key, bool(value)))
                    elif isinstance(node, genicam.IInteger):
                        applied[key] = int(self._set(key, int(value)))
                    else:
                        applied[key] = float(self._set(key, float(value)))
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
        if roi_keys:
            try:
                roi = self._set_roi_nodes(int(roi_keys.get("offset_x", self._get("OffsetX", 0))), int(roi_keys.get("offset_y", self._get("OffsetY", 0))),
                                          int(roi_keys.get("width", self._get("Width", 0))), int(roi_keys.get("height", self._get("Height", 0))))
                applied.update({"offset_x": roi.x, "offset_y": roi.y, "width": roi.w, "height": roi.h})
            except Exception as exc:  # noqa: BLE001
                errors["roi"] = str(exc)
        if errors:
            raise CameraParamError(errors)
        return applied

    def apply_roi(self, roi: Roi, hardware: bool) -> tuple[bool, Roi]:
        if self.cam is None:
            return False, roi
        if not hardware:
            self._set_roi_nodes(0, 0, int(self._node("Width").GetMax()), int(self._node("Height").GetMax()))
            return False, roi
        if roi.is_full():
            self._set_roi_nodes(0, 0, int(self._node("Width").GetMax()), int(self._node("Height").GetMax()))
            return True, Roi()
        return True, self._set_roi_nodes(roi.x, roi.y, roi.w, roi.h)

    def describe(self) -> DeviceDescription:
        sw = int(self._get("SensorWidth", 0) or (self._node("Width").GetMax() if self._node("Width") else 0))
        sh = int(self._get("SensorHeight", 0) or (self._node("Height").GetMax() if self._node("Height") else 0))
        pf = self._node("PixelFormat")
        formats = list(pf.Symbolics) if pf is not None else []
        return DeviceDescription("basler", self._model, self._serial, sw, sh, formats, True, self._node("TriggerMode") is not None, self._node("TriggerMode") is not None,
                                 any(f.startswith(("Bayer", "BGR", "RGB", "YUV")) for f in formats))
