"""IDS 相機（IDS peak：ids_peak＋ids_peak_ipl）。裝置以序號指定（`serial:<sn>`）；支援硬體 ROI、軟體／硬體觸發。

客戶端 PC 必須安裝 IDS peak 執行期（GenTL producer 與 USB3／GigE 驅動）；pip 的 ids_peak 只是綁定。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec, align
from vscapture.config import Roi

log = logging.getLogger(__name__)

try:
    from ids_peak import ids_peak  # type: ignore
    from ids_peak import ids_peak_ipl_extension  # type: ignore
    from ids_peak_ipl import ids_peak_ipl  # type: ignore

    _IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001
    ids_peak = None
    ids_peak_ipl = None
    ids_peak_ipl_extension = None
    _IMPORT_ERROR = str(exc)

_initialized = False
EXTRA_NODES = ("ExposureAuto", "GainAuto", "BalanceWhiteAuto", "Gamma", "BlackLevel", "ReverseX", "ReverseY", "BinningHorizontal", "BinningVertical",
               "TriggerDelay", "DeviceLinkThroughputLimit")


def _init() -> None:
    global _initialized
    if not _initialized:
        ids_peak.Library.Initialize()
        _initialized = True


class IdsPeakCamera(Camera):
    backend = "ids"
    label = "IDS peak"

    def __init__(self) -> None:
        self.device: Any = None
        self.nodemap: Any = None
        self.stream: Any = None
        self.converter: Any = None
        self._serial = ""
        self._model = ""
        self._running = False
        self._trigger = "freerun"
        self._mono = True

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return (True, "") if ids_peak is not None else (False, f"尚未安裝 ids_peak／IDS peak 執行期（{_IMPORT_ERROR}）")

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        if ids_peak is None:
            return []
        _init()
        dm = ids_peak.DeviceManager.Instance()
        dm.Update()
        out: list[DeviceInfo] = []
        for d in dm.Devices():
            out.append(DeviceInfo("ids", f"serial:{d.SerialNumber()}", d.DisplayName(), model=d.ModelName(), serial=d.SerialNumber(), extra={"openable": bool(d.IsOpenable())}))
        return out

    # ---- 節點 ----
    def _node(self, name: str) -> Any:
        try:
            return self.nodemap.FindNode(name)
        except Exception:  # noqa: BLE001
            return None

    def _get(self, name: str, default: Any = None) -> Any:
        node = self._node(name)
        if node is None:
            return default
        try:
            if node.Type() == ids_peak.NodeType_Enumeration:
                return node.CurrentEntry().SymbolicValue()
            return node.Value()
        except Exception:  # noqa: BLE001
            return default

    def _set(self, name: str, value: Any) -> Any:
        node = self._node(name)
        if node is None:
            raise ValueError(f"{name} 不存在")
        if node.Type() == ids_peak.NodeType_Enumeration:
            node.SetCurrentEntry(str(value))
            return node.CurrentEntry().SymbolicValue()
        if node.Type() == ids_peak.NodeType_Command:
            node.Execute()
            node.WaitUntilDone()
            return None
        node.SetValue(value)
        return node.Value()

    def open(self, device_id: str) -> DeviceDescription:
        if ids_peak is None:
            raise CameraError(f"尚未安裝 ids_peak（{_IMPORT_ERROR}）")
        _init()
        serial = str(device_id).split(":")[-1]
        dm = ids_peak.DeviceManager.Instance()
        dm.Update()
        found = next((d for d in dm.Devices() if d.SerialNumber() == serial), None)
        if found is None:
            raise CameraError(f"找不到序號 {serial} 的 IDS 相機")
        if not found.IsOpenable():
            raise CameraError("相機被其他程式佔用")
        self.device = found.OpenDevice(ids_peak.DeviceAccessType_Control)
        self.nodemap = self.device.RemoteDevice().NodeMaps()[0]
        try:
            self._set("UserSetSelector", "Default")
            self._set("UserSetLoad", None)
        except Exception:  # noqa: BLE001
            pass
        self.stream = self.device.DataStreams()[0].OpenDataStream()
        self._serial, self._model = serial, found.ModelName()
        self._refresh_converter()
        return self.describe()

    def _refresh_converter(self) -> None:
        fmt = str(self._get("PixelFormat", "Mono8"))
        self._mono = fmt.startswith("Mono")
        self.converter = ids_peak_ipl.ImageConverter()

    def _alloc(self) -> None:
        payload = int(self._node("PayloadSize").Value())
        n = max(int(self.stream.NumBuffersAnnouncedMinRequired()), 3)
        for _ in range(n):
            buf = self.stream.AllocAndAnnounceBuffer(payload)
            self.stream.QueueBuffer(buf)

    def _revoke(self) -> None:
        try:
            self.stream.Flush(ids_peak.DataStreamFlushMode_DiscardAll)
            for b in self.stream.AnnouncedBuffers():
                self.stream.RevokeBuffer(b)
        except Exception:  # noqa: BLE001
            pass

    def start(self) -> None:
        if self.device is None:
            raise CameraError("相機尚未開啟")
        if self._running:
            return
        self._alloc()
        self._set("TLParamsLocked", 1)
        self.stream.StartAcquisition(ids_peak.AcquisitionStartMode_Default, ids_peak.DataStream.INFINITE_NUMBER)
        self._set("AcquisitionStart", None)
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        try:
            self._set("AcquisitionStop", None)
            self.stream.StopAcquisition(ids_peak.AcquisitionStopMode_Default)
        finally:
            self._revoke()
            try:
                self._set("TLParamsLocked", 0)
            except Exception:  # noqa: BLE001
                pass
            self._running = False

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self.stream = None
            self.nodemap = None
            self.device = None

    @property
    def is_open(self) -> bool:
        return self.device is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def trigger_mode(self) -> str:
        return self._trigger

    def _origin(self) -> tuple[int, int]:
        return int(self._get("OffsetX", 0) or 0), int(self._get("OffsetY", 0) or 0)

    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        if not self._running:
            return None
        try:
            buf = self.stream.WaitForFinishedBuffer(int(timeout * 1000))
        except ids_peak.Exception:
            return None
        try:
            img = ids_peak_ipl_extension.BufferToImage(buf)
            out = self.converter.Convert(img, ids_peak_ipl.PixelFormatName_Mono8 if self._mono else ids_peak_ipl.PixelFormatName_BGR8)
            arr = out.get_numpy_2D().copy() if self._mono else out.get_numpy_3D().copy()
        finally:
            self.stream.QueueBuffer(buf)
        return arr, self._origin()

    def snap(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]]:
        if not self._running:
            self.start()
        if self._trigger == "software":
            self._set("TriggerSoftware", None)
        got = self.grab_one(timeout)
        if got is None:
            raise CameraError("擷取逾時")
        return got

    # ---- 參數 ----
    def _spec(self, name: str, key: str | None = None, label: str = "", standard: bool = False) -> ParamSpec | None:
        node = self._node(name)
        if node is None:
            return None
        key = key or name
        try:
            access = node.AccessStatus()
            writable = access in (ids_peak.NodeAccessStatus_ReadWrite, ids_peak.NodeAccessStatus_WriteOnly)
            t = node.Type()
            if t == ids_peak.NodeType_Enumeration:
                choices = [e.SymbolicValue() for e in node.Entries() if e.AccessStatus() in (ids_peak.NodeAccessStatus_ReadOnly, ids_peak.NodeAccessStatus_ReadWrite)]
                return ParamSpec(key, "enum", node.CurrentEntry().SymbolicValue(), choices=choices, writable=writable, standard=standard, label=label or name, group="" if standard else "進階")
            if t == ids_peak.NodeType_Boolean:
                return ParamSpec(key, "bool", bool(node.Value()), writable=writable, standard=standard, label=label or name, group="" if standard else "進階")
            if t == ids_peak.NodeType_Integer:
                return ParamSpec(key, "int", int(node.Value()), int(node.Minimum()), int(node.Maximum()), int(node.Increment()), writable=writable, standard=standard, label=label or name, group="" if standard else "進階")
            if t == ids_peak.NodeType_Float:
                return ParamSpec(key, "float", float(node.Value()), float(node.Minimum()), float(node.Maximum()), None, unit=str(node.Unit() or ""), writable=writable, standard=standard, label=label or name, group="" if standard else "進階")
            if t == ids_peak.NodeType_Command:
                return ParamSpec(key, "command", None, writable=writable, label=label or name, group="進階")
        except Exception:  # noqa: BLE001
            return None
        return None

    def get_params(self) -> dict[str, ParamSpec]:
        if self.nodemap is None:
            return {}
        out: dict[str, ParamSpec] = {}
        for node, key, label in (("ExposureTime", "exposure_us", "曝光時間"), ("Gain", "gain_db", "增益"), ("AcquisitionFrameRate", "fps", "影格率"), ("PixelFormat", "pixel_format", "像素格式"),
                                 ("Width", "width", "寬"), ("Height", "height", "高"), ("OffsetX", "offset_x", "X 位移"), ("OffsetY", "offset_y", "Y 位移")):
            spec = self._spec(node, key, label, standard=True)
            if spec:
                if key == "exposure_us":
                    spec.unit = "µs"
                out[key] = spec
        modes = ["freerun"] + (["software", "hardware"] if self._node("TriggerMode") is not None else [])
        out["trigger_mode"] = ParamSpec("trigger_mode", "enum", self._trigger, choices=modes, standard=True, label="觸發模式")
        for name in EXTRA_NODES:
            spec = self._spec(name)
            if spec:
                out[name] = spec
        return out

    def _set_roi_nodes(self, x: int, y: int, w: int, h: int) -> Roi:
        was = self._running
        if was:
            self.stop()
        try:
            self._set("OffsetX", 0)
            self._set("OffsetY", 0)
            wn, hn = self._node("Width"), self._node("Height")
            w = align(w, int(wn.Minimum()), int(wn.Maximum()), int(wn.Increment()))
            h = align(h, int(hn.Minimum()), int(hn.Maximum()), int(hn.Increment()))
            self._set("Width", w)
            self._set("Height", h)
            xn, yn = self._node("OffsetX"), self._node("OffsetY")
            x = align(x, int(xn.Minimum()), int(xn.Maximum()), int(xn.Increment()))
            y = align(y, int(yn.Minimum()), int(yn.Maximum()), int(yn.Increment()))
            self._set("OffsetX", x)
            self._set("OffsetY", y)
        finally:
            if was:
                self.start()
        return Roi(x, y, w, h)

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.nodemap is None:
            raise CameraError("相機尚未開啟")
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        roi_keys = {k: v for k, v in values.items() if k in ("width", "height", "offset_x", "offset_y")}
        for key, value in values.items():
            if key in roi_keys:
                continue
            try:
                if key == "exposure_us":
                    applied[key] = float(self._set("ExposureTime", float(value)))
                elif key == "gain_db":
                    if self._node("GainSelector") is not None:
                        self._set("GainSelector", "AnalogAll")
                    applied[key] = float(self._set("Gain", float(value)))
                elif key == "fps":
                    if self._node("AcquisitionFrameRateTargetEnable") is not None:
                        self._set("AcquisitionFrameRateTargetEnable", True)
                    applied[key] = float(self._set("AcquisitionFrameRate", float(value)))
                elif key == "pixel_format":
                    was = self._running
                    if was:
                        self.stop()  # PayloadSize 會變，緩衝要重配
                    applied[key] = str(self._set("PixelFormat", str(value)))
                    self._refresh_converter()
                    if was:
                        self.start()
                elif key == "trigger_mode":
                    mode = str(value)
                    if mode not in ("freerun", "software", "hardware"):
                        raise ValueError("觸發模式無效")
                    self._set("TriggerSelector", "ExposureStart")
                    self._set("TriggerMode", "Off" if mode == "freerun" else "On")
                    if mode != "freerun":
                        self._set("TriggerSource", "Software" if mode == "software" else "Line0")
                    self._trigger = mode
                    applied[key] = mode
                else:
                    node = self._node(key)
                    if node is None:
                        raise ValueError("沒有此節點")
                    t = node.Type()
                    if t == ids_peak.NodeType_Boolean:
                        applied[key] = bool(self._set(key, bool(value)))
                    elif t == ids_peak.NodeType_Integer:
                        applied[key] = int(self._set(key, int(value)))
                    elif t == ids_peak.NodeType_Float:
                        applied[key] = float(self._set(key, float(value)))
                    else:
                        applied[key] = self._set(key, value)
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
        if self.nodemap is None:
            return False, roi
        wmax, hmax = int(self._node("Width").Maximum()), int(self._node("Height").Maximum())
        if not hardware or roi.is_full():
            self._set_roi_nodes(0, 0, wmax, hmax)
            return (hardware, Roi()) if hardware else (False, roi)
        return True, self._set_roi_nodes(roi.x, roi.y, roi.w, roi.h)

    def describe(self) -> DeviceDescription:
        sw = int(self._get("SensorWidth", 0) or self._get("WidthMax", 0) or 0)
        sh = int(self._get("SensorHeight", 0) or self._get("HeightMax", 0) or 0)
        pf = self._spec("PixelFormat")
        formats = pf.choices if pf else []
        return DeviceDescription("ids", self._model, self._serial, sw, sh, formats, True, self._node("TriggerMode") is not None, self._node("TriggerMode") is not None,
                                 any(f.startswith(("Bayer", "BGR", "RGB")) for f in formats))
