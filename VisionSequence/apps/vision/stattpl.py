"""統計範本（statistical template）：N 張良品建逐像素 mean／std 模型，給 defect_stat 工具比對。

defect_diff 是單張良品比對，對正常變異（打光波動、材質紋理、位置微移）容忍度差；改成 N 張良品的逐像素統計，
每個像素有自己的「正常範圍」，紋理區寬、平坦區窄，穩定度差一個量級。

資產格式：npz（Asset.kind="file"），鍵：
  mean  float32 (H, W)   對齊後的逐像素平均
  std   float32 (H, W)   逐像素標準差
  valid uint8   (H, W)   255＝每張對齊後都落在影像內（且在 ROI 遮罩內）的像素
  n     int              樣本數
  offset [x0, y0]        建模時 ROI 在來源影像的左上角（工具用來核對 ROI 尺寸與位置）
  region JSON 字串        建模用的 ROI（可為 null）
  align  str             none｜phase
  shifts float32 (N, 2)  每張對齊到第一張的位移
  version int
meta（Asset.meta）：samples、width、height、align、shift_max／shift_mean、std_p50／p90／p99／mean、valid_ratio、offset。

載入走模組層快取（mtime＋size 判失效，同 locate._ASSET_CACHE 的作法），工具每次 run 只剩查表。
"""

from __future__ import annotations

import io
import json
import os
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.roi import crop as roi_crop

VERSION = 1
MIN_SAMPLES = 3
RECOMMENDED_SAMPLES = 10


class StatTemplateError(ValueError):
    """建模／載入時的可預期錯誤（訊息給使用者看，英文）。"""


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.dtype != np.uint8:
        from apps.vision.tools import imgfmt

        image = imgfmt.normalize_u8(image)
    return image


def _phase_shift(reference_f32: np.ndarray, image_f32: np.ndarray, window: np.ndarray) -> tuple[float, float, float]:
    """cv2.phaseCorrelate 給了 window 時會把**尺寸已是 DFT 最佳尺寸**的輸入就地乘上視窗（copyMakeBorder 不需補邊就直接用原陣列），
    所以參考影像每次都給複本，否則第二張起就對著被視窗壓過的參考在對齊。"""
    (dx, dy), resp = cv2.phaseCorrelate(np.array(reference_f32, copy=True), image_f32, window)
    return float(dx), float(dy), float(resp)


def build(images: list[np.ndarray], region: dict[str, Any] | None = None, align: str = "phase", max_shift: float = 0.0) -> tuple[dict[str, Any], dict[str, Any]]:
    """N 張良品 → (payload, meta)。

    每張先轉灰階、依 region 裁切（尺寸必須一致），第 2 張起用相位相關對到第 1 張（align="phase"）；
    對齊後落在影像外的像素在 valid 標 0（連同 ROI 遮罩外）。max_shift > 0 時位移超過它的樣本視為對齊失敗而剔除。
    """
    if len(images) < MIN_SAMPLES:
        raise StatTemplateError(f"At least {MIN_SAMPLES} good images are needed ({len(images)} given); {RECOMMENDED_SAMPLES} or more is recommended")
    align = "phase" if align == "phase" else "none"
    crops = []
    mask = None
    offset = (0, 0)
    for i, img in enumerate(images):
        g = _gray(np.asarray(img))
        c = roi_crop(g, region)
        if c.image.size == 0:
            raise StatTemplateError(f"Image {i + 1}: the region falls outside the image")
        if i == 0:
            offset = (c.x0, c.y0)
            mask = c.mask
        elif c.image.shape != crops[0].shape:
            raise StatTemplateError(f"Image {i + 1} is {c.image.shape[1]}×{c.image.shape[0]} after cropping but image 1 is {crops[0].shape[1]}×{crops[0].shape[0]}; every good image must be the same size")
        crops.append(np.ascontiguousarray(c.image))
    h, w = crops[0].shape
    ref = crops[0].astype(np.float32)
    window = cv2.createHanningWindow((w, h), cv2.CV_32F) if align == "phase" and min(h, w) >= 8 else None
    acc = np.zeros((h, w), dtype=np.float64)
    acc2 = np.zeros((h, w), dtype=np.float64)
    valid = np.full((h, w), 255, dtype=np.uint8)
    shifts: list[list[float]] = []
    responses: list[float] = []
    used = 0
    dropped = 0
    ones = np.full((h, w), 255, dtype=np.uint8)
    for i, sub in enumerate(crops):
        dx = dy = 0.0
        if window is not None and i > 0:
            dx, dy, resp = _phase_shift(ref, sub.astype(np.float32), window)
            responses.append(resp)
            if max_shift > 0 and (abs(dx) > max_shift or abs(dy) > max_shift):
                dropped += 1
                continue
        if dx or dy:
            m = np.array([[1, 0, -dx], [0, 1, -dy]], dtype=np.float32)
            aligned = cv2.warpAffine(sub, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            inside = cv2.warpAffine(ones, m, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            cv2.bitwise_and(valid, inside, dst=valid)
        else:
            aligned = sub
        a = aligned.astype(np.float64)
        acc += a
        acc2 += a * a
        shifts.append([dx, dy])
        used += 1
    if used < MIN_SAMPLES:
        raise StatTemplateError(f"Only {used} images aligned within {max_shift:g} px; at least {MIN_SAMPLES} are needed")
    mean = acc / used
    var = np.maximum(acc2 / used - mean * mean, 0.0)
    std = np.sqrt(var)
    if mask is not None:
        cv2.bitwise_and(valid, mask, dst=valid)
    payload = {
        "mean": mean.astype(np.float32), "std": std.astype(np.float32), "valid": valid, "n": int(used),
        "offset": np.array(offset, dtype=np.int32), "region": json.dumps(region) if region else "null", "align": align,
        "shifts": np.asarray(shifts, dtype=np.float32).reshape(-1, 2), "version": VERSION,
    }
    meta = describe(payload, responses=responses, dropped=dropped)
    return payload, meta


def describe(payload: dict[str, Any], responses: list[float] | None = None, dropped: int = 0) -> dict[str, Any]:
    """資產 meta：樣本數、尺寸、對齊殘差統計、std 分位數、有效比例。"""
    std = np.asarray(payload["std"], dtype=np.float32)
    valid = np.asarray(payload["valid"], dtype=np.uint8) > 0
    shifts = np.asarray(payload.get("shifts", np.zeros((0, 2))), dtype=np.float32).reshape(-1, 2)
    mags = np.hypot(shifts[:, 0], shifts[:, 1]) if len(shifts) else np.zeros(0)
    sv = std[valid] if valid.any() else std.reshape(-1)
    h, w = std.shape
    off = np.asarray(payload.get("offset", [0, 0])).tolist()
    meta = {
        "kind": "stat_template", "version": int(payload.get("version", VERSION)), "samples": int(payload["n"]), "width": int(w), "height": int(h),
        "align": str(payload.get("align", "phase")), "offset": [int(off[0]), int(off[1])],
        "shift_max": round(float(mags.max()), 3) if len(mags) else 0.0, "shift_mean": round(float(mags.mean()), 3) if len(mags) else 0.0,
        "std_p50": round(float(np.percentile(sv, 50)), 3), "std_p90": round(float(np.percentile(sv, 90)), 3),
        "std_p99": round(float(np.percentile(sv, 99)), 3), "std_mean": round(float(sv.mean()), 3),
        "valid_ratio": round(float(valid.mean()), 4), "dropped": int(dropped),
    }
    if responses:
        meta["align_response_min"] = round(float(min(responses)), 4)
    region = payload.get("region")
    if isinstance(region, str) and region not in ("", "null"):
        try:
            meta["region"] = json.loads(region)
        except json.JSONDecodeError:
            pass
    return meta


def save(path: str, payload: dict[str, Any]) -> int:
    """寫成 npz（支援非 ASCII 路徑），回傳位元組數。"""
    buf = io.BytesIO()
    np.savez_compressed(buf, **payload)
    data = buf.getvalue()
    with open(path, "wb") as fh:
        fh.write(data)
    invalidate(path)
    return len(data)


_CACHE: "OrderedDict[str, tuple[float, int, dict[str, Any]]]" = OrderedDict()
_CACHE_MAX = 16
_LOCK = threading.Lock()


def invalidate(path: str = "") -> None:
    with _LOCK:
        if path:
            _CACHE.pop(path, None)
        else:
            _CACHE.clear()


def load(path: str) -> dict[str, Any]:
    """載入 npz（模組層快取，mtime＋size 判失效）。回傳的陣列是共用的，呼叫端不可原地修改。"""
    try:
        st = os.stat(path)
    except OSError as exc:
        raise StatTemplateError(f"Could not read the statistical template: {exc}") from None
    with _LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            _CACHE.move_to_end(path)
            return hit[2]
    try:
        with np.load(path, allow_pickle=False) as z:
            if "mean" not in z or "std" not in z:
                raise StatTemplateError("This file is not a statistical template (no mean/std maps)")
            payload = {
                "mean": np.ascontiguousarray(z["mean"], dtype=np.float32), "std": np.ascontiguousarray(z["std"], dtype=np.float32),
                "valid": np.ascontiguousarray(z["valid"], dtype=np.uint8) if "valid" in z else np.full(z["mean"].shape, 255, np.uint8),
                "n": int(z["n"]) if "n" in z else 0, "offset": z["offset"].tolist() if "offset" in z else [0, 0],
                "region": str(z["region"]) if "region" in z else "null", "align": str(z["align"]) if "align" in z else "phase",
                "shifts": z["shifts"] if "shifts" in z else np.zeros((0, 2), np.float32), "version": int(z["version"]) if "version" in z else 1,
            }
    except (OSError, ValueError, KeyError) as exc:
        raise StatTemplateError(f"Could not read the statistical template: {exc}") from None
    payload["region_dict"] = None
    if payload["region"] not in ("", "null"):
        try:
            payload["region_dict"] = json.loads(payload["region"])
        except json.JSONDecodeError:
            payload["region_dict"] = None
    with _LOCK:
        _CACHE[path] = (st.st_mtime, st.st_size, payload)
        _CACHE.move_to_end(path)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return payload


def from_asset(asset_id: Any, resolve: Any) -> dict[str, Any]:
    """資產 id → payload（resolve＝ctx.asset_path）。"""
    if not asset_id:
        raise StatTemplateError("No statistical template is set")
    path = resolve(str(asset_id))
    if not path:
        raise StatTemplateError(f"Asset {asset_id} not found")
    return load(path)


def deviation_map(image: np.ndarray, payload: dict[str, Any], floor: float, direction: str = "both") -> np.ndarray:
    """(image − mean) / max(std, floor)，依 direction 取號：both＝絕對值、darker＝mean − image、brighter＝image − mean。float32。"""
    mean = payload["mean"]
    std = payload["std"]
    denom = np.maximum(std, np.float32(max(1e-3, floor)))
    f = image.astype(np.float32) if image.dtype != np.float32 else image
    dev = cv2.subtract(f, mean)
    if direction == "darker":
        cv2.multiply(dev, -1.0, dst=dev)
    elif direction != "brighter":
        dev = cv2.absdiff(f, mean)
    cv2.divide(dev, denom, dst=dev)
    return dev
