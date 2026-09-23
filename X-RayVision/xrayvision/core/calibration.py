"""
影像校正與吸收量轉換 (成像條件對策第一層)

16-bit 原始影像：
  1. (選用) 暗場／平場校正：I' = (I - D) / (F - D) x mean(F - D)，扣除偵測器暗電流與增益不均勻。
     校正檔以「校正設定檔」管理，依拍攝條件 (管電壓、模式等) 分組，由配方指定使用哪一組。
  2. 取 -ln(I) 成為吸收量：曝光、管電流改變只造成整體偏移，重疊材料的吸收可相加。
8-bit 轉存影像灰階已被拉伸，無法還原吸收量，只能去噪後以 (255 - I) / 255 近似，且不套用平場校正。
不採用直方圖匹配等「讓影像看起來一樣」的做法 (會破壞灰階的定量關係)。
"""
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .io import KIND_RAW16, load_image

DEFAULTS = dict(
    raw_sigma=1.0,      # 16-bit：取對數前的高斯去噪
    rgb_median=5,       # 8-bit：中值去除抖動雜訊
    rgb_sigma=2.0,      # 8-bit：再高斯
)


class CalibrationError(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Prepared:
    absorption: np.ndarray    # float32，越大代表吸收越多 (越暗)
    display: np.ndarray       # uint8 灰階，顯示與疊圖用
    smoothed: np.ndarray      # 去噪 (與校正) 後的灰階 (float32)
    calibration: dict = None  # 使用的校正設定檔摘要


@dataclass
class CalibrationProfile:
    """暗場／平場校正設定檔；影像以 float32 .npy 保存於設定檔資料夾"""
    profile_id: str
    created_at: str
    conditions: dict = field(default_factory=dict)    # 對應的拍攝條件 (管電壓、模式等)
    shape: tuple = None
    dark_frames: int = 0
    flat_frames: int = 0
    note: str = ""
    dark: np.ndarray = field(default=None, repr=False)
    flat: np.ndarray = field(default=None, repr=False)

    def summary(self):
        return dict(profile_id=self.profile_id, created_at=self.created_at, conditions=self.conditions,
                    dark_frames=self.dark_frames, flat_frames=self.flat_frames)

    def apply(self, I):
        if tuple(I.shape) != tuple(self.shape):
            raise CalibrationError("calibration_shape_mismatch", f"{I.shape} vs {self.shape}")
        D = self.dark if self.dark is not None else 0.0
        gain = self.flat - D
        ref = float(np.mean(gain))
        return (I - D) / np.maximum(gain, 1e-3 * ref) * ref

    # ---- 保存與讀取 ----
    def save(self, root):
        d = os.path.join(root, self.profile_id)
        os.makedirs(d, exist_ok=True)
        meta = {k: v for k, v in asdict(self).items() if k not in ("dark", "flat")}
        meta["shape"] = list(self.shape)
        with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        np.save(os.path.join(d, "flat.npy"), self.flat.astype(np.float32))
        if self.dark is not None:
            np.save(os.path.join(d, "dark.npy"), self.dark.astype(np.float32))
        return d

    @classmethod
    def load(cls, root, profile_id):
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", profile_id or ""):
            raise CalibrationError("invalid_calibration_id", profile_id)
        d = os.path.join(root, profile_id)
        try:
            with open(os.path.join(d, "profile.json"), encoding="utf-8") as f:
                meta = json.load(f)
            flat = np.load(os.path.join(d, "flat.npy"))
        except OSError:
            raise CalibrationError("calibration_not_found", profile_id)
        dark_p = os.path.join(d, "dark.npy")
        dark = np.load(dark_p) if os.path.isfile(dark_p) else None
        meta["shape"] = tuple(meta["shape"])
        return cls(dark=dark, flat=flat, **meta)

    @classmethod
    def build(cls, profile_id, flat_paths, dark_paths=(), conditions=None, note=""):
        """由多張空拍 (平場) 與暗場影像平均建立設定檔；只接受 16-bit 原始影像"""
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", profile_id or ""):
            raise CalibrationError("invalid_calibration_id", profile_id)
        flat = _average(flat_paths)
        dark = _average(dark_paths) if dark_paths else None
        if dark is not None and dark.shape != flat.shape:
            raise CalibrationError("calibration_shape_mismatch", f"{dark.shape} vs {flat.shape}")
        return cls(profile_id=profile_id, created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   conditions=dict(conditions or {}), shape=tuple(flat.shape), dark_frames=len(dark_paths),
                   flat_frames=len(flat_paths), note=note, dark=dark, flat=flat)


def _average(paths):
    if not paths:
        raise CalibrationError("calibration_no_frames")
    acc = None
    for p in paths:
        img = load_image(p)
        if img.kind != KIND_RAW16:
            raise CalibrationError("calibration_requires_raw", p)
        a = img.pixels.astype(np.float64)
        if acc is not None and a.shape != acc.shape:
            raise CalibrationError("calibration_shape_mismatch", p)
        acc = a if acc is None else acc + a
    return (acc / len(paths)).astype(np.float32)


def prepare(image, cfg=None, profile=None):
    c = dict(DEFAULTS, **(cfg or {}))
    g = image.pixels
    if image.kind == KIND_RAW16:
        I = g.astype(np.float32)
        if profile is not None:
            I = profile.apply(I).astype(np.float32)
        f = cv2.GaussianBlur(I, (0, 0), c["raw_sigma"])
        A = -np.log(np.maximum(f, 1.0) / 65535.0)
    else:
        f = cv2.GaussianBlur(cv2.medianBlur(g, c["rgb_median"]).astype(np.float32), (0, 0), c["rgb_sigma"])
        A = (255.0 - f) / 255.0
    return Prepared(absorption=A.astype(np.float32), display=to_display(f), smoothed=f,
                    calibration=profile.summary() if (profile is not None and image.kind == KIND_RAW16) else None)


def to_display(f, lo_pct=0.5, hi_pct=99.5):
    lo, hi = np.percentile(f, [lo_pct, hi_pct])
    return np.clip((f - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
